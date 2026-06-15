import csv
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, TextIOWrapper
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from backend.app.application_metadata import (
    PRODUCT_ORIGIN_FIELD,
    RESPONSIBLE_PARTY_FIELD,
    ApplicationMetadataError,
    normalize_and_validate_responsible_party_metadata,
)

ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_IMAGE_PIXELS = 30_000_000
REQUIRED_MANIFEST_COLUMNS = {
    "filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    RESPONSIBLE_PARTY_FIELD,
    PRODUCT_ORIGIN_FIELD,
}
REQUIRED_MANIFEST_TEXT_COLUMNS = (
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    RESPONSIBLE_PARTY_FIELD,
    PRODUCT_ORIGIN_FIELD,
)
OPTIONAL_MANIFEST_TEXT_COLUMNS = (
    "cola_id",
    "fanciful_name",
    "formula",
    "grape_varietals",
    "wine_appellation",
    "serial_number",
    "producer",
    "country_of_origin",
)
BACK_IMAGE_TOKENS = {"back", "rear", "reverse", "verso"}
FRONT_IMAGE_TOKENS = {"front", "primary", "main", "face", "brand"}
FIRST_SIDE_NUMBER_TOKENS = {"1", "01", "001"}
SECOND_SIDE_NUMBER_TOKENS = {"2", "02", "002"}
SIDE_IMAGE_TOKENS = BACK_IMAGE_TOKENS | {
    *FRONT_IMAGE_TOKENS,
    "label",
    "labels",
    "scan",
    "image",
    "photo",
    "side",
    "or",
    "keg",
    "collar",
}
SIDE_NUMBER_TOKENS = FIRST_SIDE_NUMBER_TOKENS | SECOND_SIDE_NUMBER_TOKENS


@dataclass(frozen=True)
class InferredBackImage:
    filename: str
    back_filename: str


@dataclass(frozen=True)
class RejectedManifestRow:
    row_number: int
    filename: str
    reason: str


@dataclass(frozen=True)
class BatchManifestParseResult:
    rows: list[dict[str, str | bytes]]
    selected_image_count: int
    accepted_image_count: int
    ignored_images: list[str]
    inferred_back_images: list[InferredBackImage]
    rejected_rows: list[RejectedManifestRow]


def _verify_image(content: bytes) -> None:
    try:
        image = Image.open(BytesIO(content))
        image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Upload is not a readable image") from exc


def save_image_bytes(
    upload_dir: Path,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[str, str]:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Upload must be PNG, JPEG, or WebP")

    _verify_image(content)
    digest = sha256(content).hexdigest()
    suffix = ALLOWED_CONTENT_TYPES.get(content_type) or Path(filename).suffix.lower() or ".png"
    directory = upload_dir / digest[:2]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}{suffix}"
    path.write_bytes(content)
    return digest, str(path)


async def save_upload(upload_dir: Path, upload: UploadFile, max_upload_mb: int) -> tuple[str, str]:
    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Upload must be PNG, JPEG, or WebP")

    content = await upload.read()
    if len(content) > max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Upload exceeds {max_upload_mb} MB")

    # Prevent decompression-bomb style inputs before storing bytes.
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    return save_image_bytes(upload_dir, upload.filename or "label", content, upload.content_type)


def save_batch_image(upload_dir: Path, filename: str, content: bytes) -> tuple[str, str]:
    content_type = mimetypes.guess_type(filename)[0] or "image/png"
    return save_image_bytes(upload_dir, filename, content, content_type)


def save_combined_label_image(upload_dir: Path, image_paths: list[str]) -> tuple[str, str]:
    opened = [Image.open(path).convert("RGB") for path in image_paths]
    try:
        max_width = max(image.width for image in opened)
        padding = 36
        total_height = sum(
            int(image.height * (max_width / image.width)) for image in opened
        ) + padding * (len(opened) + 1)
        canvas = Image.new("RGB", (max_width + padding * 2, total_height), "white")
        y_offset = padding
        for image in opened:
            scaled_height = int(image.height * (max_width / image.width))
            resized = image.resize((max_width, scaled_height))
            canvas.paste(resized, (padding, y_offset))
            y_offset += scaled_height + padding

        buffer = BytesIO()
        canvas.save(buffer, format="PNG")
        return save_image_bytes(
            upload_dir,
            "front-back-verification.png",
            buffer.getvalue(),
            "image/png",
        )
    finally:
        for image in opened:
            image.close()


def parse_manifest_zip(content: bytes) -> BatchManifestParseResult:
    try:
        with ZipFile(BytesIO(content)) as archive:
            if "manifest.csv" not in archive.namelist():
                raise ValueError("Batch ZIP must include manifest.csv")
            with archive.open("manifest.csv") as manifest_file:
                rows = list(csv.DictReader(TextIOWrapper(manifest_file, encoding="utf-8")))
            image_lookup = {
                name: archive.read(name)
                for name in archive.namelist()
                if name != "manifest.csv"
            }
            return _parse_manifest_rows(
                rows,
                image_lookup,
                missing_image_message="Manifest image not found in ZIP",
                missing_back_image_message="Manifest back image not found in ZIP",
            )
    except BadZipFile as exc:
        raise ValueError("Batch upload must be a readable ZIP file") from exc


def parse_manifest_files(
    manifest_content: bytes,
    image_lookup: Mapping[str, bytes],
) -> BatchManifestParseResult:
    rows = list(csv.DictReader(TextIOWrapper(BytesIO(manifest_content), encoding="utf-8-sig")))
    return _parse_manifest_rows(
        rows,
        image_lookup,
        missing_image_message="Manifest image not found in selected files",
        missing_back_image_message="Manifest back image not found in selected files",
    )


def _parse_manifest_rows(
    rows: list[dict],
    image_lookup: Mapping[str, bytes],
    *,
    missing_image_message: str,
    missing_back_image_message: str,
) -> BatchManifestParseResult:
    parsed: list[dict[str, str | bytes]] = []
    used_image_keys: set[str] = set()
    inferred_back_images: list[InferredBackImage] = []
    rejected_rows: list[RejectedManifestRow] = []
    for index, row in enumerate(rows, start=1):
        present_columns = {key for key in row if isinstance(key, str)}
        missing = REQUIRED_MANIFEST_COLUMNS - present_columns
        if missing:
            raise ValueError(f"Manifest missing columns: {', '.join(sorted(missing))}")
        try:
            parsed_row, row_image_keys, split_back_from_filename = _parse_manifest_row(
                row,
                index,
                image_lookup,
                missing_image_message=missing_image_message,
                missing_back_image_message=missing_back_image_message,
                present_columns=present_columns,
            )
        except ManifestRowRejected as exc:
            rejected_rows.append(
                RejectedManifestRow(
                    row_number=index,
                    filename=exc.filename,
                    reason=str(exc),
                )
            )
            continue
        used_image_keys.update(row_image_keys)
        if split_back_from_filename:
            inferred_back_images.append(
                InferredBackImage(
                    filename=str(parsed_row["filename"]),
                    back_filename=str(parsed_row["back_filename"]),
                )
            )
        parsed.append(parsed_row)
    inferred_back_images.extend(
        _infer_back_images(
            parsed,
            image_lookup,
            used_image_keys,
        )
    )
    return BatchManifestParseResult(
        rows=parsed,
        selected_image_count=len(image_lookup),
        accepted_image_count=len(used_image_keys),
        ignored_images=[filename for filename in image_lookup if filename not in used_image_keys],
        inferred_back_images=inferred_back_images,
        rejected_rows=rejected_rows,
    )


class ManifestRowRejected(ValueError):
    def __init__(self, reason: str, *, filename: str) -> None:
        super().__init__(reason)
        self.filename = filename


def _parse_manifest_row(
    row: dict,
    index: int,
    image_lookup: Mapping[str, bytes],
    *,
    missing_image_message: str,
    missing_back_image_message: str,
    present_columns: set[str],
) -> tuple[dict[str, str | bytes], set[str], bool]:
    row = _repair_legacy_row_pasted_under_extended_template(row, image_lookup, present_columns)
    _raise_for_extra_manifest_values(row, index)
    _raise_for_absorbed_back_filename(row, index, image_lookup, present_columns)
    filename = (row.get("filename") or "").strip()
    back_filename = (row.get("back_filename") or "").strip()
    filename, back_filename, split_back_from_filename = _split_filename_cell(
        filename,
        back_filename,
        image_lookup,
        row_index=index,
    )
    if not filename:
        raise ManifestRowRejected(
            f"Manifest row {index} filename is required",
            filename="",
        )
    image_key = _find_manifest_image_key(image_lookup, filename)
    if image_key is None:
        raise ManifestRowRejected(
            f"{missing_image_message}: {filename}",
            filename=filename,
        )
    image_bytes = image_lookup[image_key]
    row_image_keys = {image_key}
    normalized_row = {**row, "filename": filename}
    for column in REQUIRED_MANIFEST_TEXT_COLUMNS:
        value = (row.get(column) or "").strip()
        if not value:
            raise ManifestRowRejected(
                f"Manifest row {index} {column} is required",
                filename=filename,
            )
        normalized_row[column] = value
    for column in OPTIONAL_MANIFEST_TEXT_COLUMNS:
        normalized_row[column] = (row.get(column) or "").strip()
    try:
        normalized_row.update(normalize_and_validate_responsible_party_metadata(normalized_row))
    except ApplicationMetadataError as exc:
        raise ManifestRowRejected(
            f"Manifest row {index} {exc.field_name} {exc.message}",
            filename=filename,
        ) from exc
    if back_filename:
        back_image_key = _find_manifest_image_key(image_lookup, back_filename)
        if back_image_key is None:
            raise ManifestRowRejected(
                f"{missing_back_image_message}: {back_filename}",
                filename=filename,
            )
        back_image_bytes = image_lookup[back_image_key]
        row_image_keys.add(back_image_key)
        normalized_row["back_filename"] = back_filename
        normalized_row["back_image_bytes"] = back_image_bytes
    return {**normalized_row, "image_bytes": image_bytes}, row_image_keys, split_back_from_filename


def _repair_legacy_row_pasted_under_extended_template(
    row: dict,
    image_lookup: Mapping[str, bytes],
    present_columns: set[str],
) -> dict:
    required_extended_columns = {"back_filename", "fanciful_name"}
    if not required_extended_columns.issubset(present_columns):
        return row

    shifted_brand = (row.get("back_filename") or "").strip()
    shifted_class = (row.get("brand_name") or "").strip()
    shifted_alcohol = (row.get("fanciful_name") or "").strip()
    shifted_net = (row.get("class_type") or "").strip()
    if not all((shifted_brand, shifted_class, shifted_alcohol, shifted_net)):
        return row
    if (row.get("alcohol_content") or "").strip() or (row.get("net_contents") or "").strip():
        return row
    if _find_manifest_image_key(image_lookup, shifted_brand) is not None:
        return row
    if not _looks_like_alcohol_content(shifted_alcohol) or not _looks_like_net_contents(
        shifted_net
    ):
        return row

    repaired = dict(row)
    repaired["back_filename"] = ""
    repaired["brand_name"] = shifted_brand
    repaired["fanciful_name"] = ""
    repaired["class_type"] = shifted_class
    repaired["alcohol_content"] = shifted_alcohol
    repaired["net_contents"] = shifted_net
    return repaired


def _looks_like_alcohol_content(value: str) -> bool:
    return re.search(r"\d+(?:\.\d+)?\s*%", value) is not None


def _looks_like_net_contents(value: str) -> bool:
    return re.search(
        r"\d+(?:\.\d+)?\s*(?:ml|mL|l|L|fl\s*oz|oz|pint|quart|gallon)s?\b",
        value,
        flags=re.I,
    ) is not None


def _raise_for_extra_manifest_values(row: dict, index: int) -> None:
    extra_values = row.get(None)
    if isinstance(extra_values, list) and any(str(value).strip() for value in extra_values):
        raise ManifestRowRejected(
            f"Manifest row {index} has extra comma-separated values. Use a back_filename "
            "column for back labels instead of adding another filename to the row.",
            filename=(row.get("filename") or "").strip(),
        )


def _raise_for_absorbed_back_filename(
    row: dict,
    index: int,
    image_lookup: Mapping[str, bytes],
    present_columns: set[str],
) -> None:
    if "back_filename" in present_columns:
        return

    filename = (row.get("filename") or "").strip()
    brand_name = (row.get("brand_name") or "").strip()
    if (
        filename
        and brand_name
        and _find_manifest_image_key(image_lookup, filename) is not None
        and _find_manifest_image_key(image_lookup, brand_name) is not None
        and _looks_like_back_image(brand_name)
    ):
        raise ManifestRowRejected(
            f"Manifest row {index} appears to put a back label filename in the brand_name "
            "column. Use a back_filename column for back labels.",
            filename=filename,
        )


def _split_filename_cell(
    filename: str,
    back_filename: str,
    image_lookup: Mapping[str, bytes],
    *,
    row_index: int,
) -> tuple[str, str, bool]:
    if back_filename or "," not in filename or _find_manifest_image_key(image_lookup, filename):
        return filename, back_filename, False

    parts = [part.strip() for part in filename.split(",") if part.strip()]
    if len(parts) == 2:
        return parts[0], parts[1], True
    raise ManifestRowRejected(
        f"Manifest row {row_index} filename contains multiple comma-separated values. "
        "Use a back_filename column for back labels.",
        filename=filename,
    )


def _find_manifest_image_key(image_lookup: Mapping[str, bytes], filename: str) -> str | None:
    if filename in image_lookup:
        return filename
    basename = Path(filename).name
    if basename in image_lookup:
        return basename
    lowercase_matches = {
        key.lower(): key
        for key in image_lookup
        if key.lower() == filename.lower() or Path(key).name.lower() == basename.lower()
    }
    if len(lowercase_matches) == 1:
        return next(iter(lowercase_matches.values()))
    return None


def _lookup_manifest_image(image_lookup: Mapping[str, bytes], filename: str) -> bytes | None:
    image_key = _find_manifest_image_key(image_lookup, filename)
    return image_lookup[image_key] if image_key is not None else None


def _infer_back_images(
    parsed: list[dict[str, str | bytes]],
    image_lookup: Mapping[str, bytes],
    used_image_keys: set[str],
) -> list[InferredBackImage]:
    inferred: list[InferredBackImage] = []
    allow_generic_front_back_pair = len(parsed) == 1
    for row in parsed:
        if row.get("back_image_bytes"):
            continue
        filename = str(row["filename"])
        candidates = [
            key
            for key in image_lookup
            if key not in used_image_keys
            and _is_matching_back_image(
                filename,
                key,
                allow_generic_front_back_pair=allow_generic_front_back_pair,
            )
        ]
        if len(candidates) != 1:
            continue
        back_filename = candidates[0]
        row["back_filename"] = back_filename
        row["back_image_bytes"] = image_lookup[back_filename]
        used_image_keys.add(back_filename)
        inferred.append(InferredBackImage(filename=filename, back_filename=back_filename))
    return inferred


def _is_matching_back_image(
    front_filename: str,
    candidate_filename: str,
    *,
    allow_generic_front_back_pair: bool,
) -> bool:
    candidate_has_back_token = _looks_like_back_image(candidate_filename)
    candidate_has_second_side_number = _has_side_number(
        candidate_filename,
        SECOND_SIDE_NUMBER_TOKENS,
    )
    if not candidate_has_back_token and not candidate_has_second_side_number:
        return False

    front_key = _filename_match_key(front_filename)
    candidate_key = _filename_match_key(candidate_filename)
    if front_key and candidate_key:
        if front_key != candidate_key:
            return False
        if candidate_has_back_token:
            return True
        return _looks_like_front_image(front_filename) or _has_side_number(
            front_filename,
            FIRST_SIDE_NUMBER_TOKENS,
        )
    return (
        candidate_has_back_token
        and allow_generic_front_back_pair
        and not front_key
        and not candidate_key
    )


def _looks_like_back_image(filename: str) -> bool:
    tokens = _filename_tokens(filename)
    return any(token in BACK_IMAGE_TOKENS for token in tokens)


def _looks_like_front_image(filename: str) -> bool:
    tokens = _filename_tokens(filename)
    return any(token in FRONT_IMAGE_TOKENS for token in tokens)


def _has_side_number(filename: str, side_numbers: set[str]) -> bool:
    tokens = _filename_tokens(filename)
    return any(token in side_numbers for token in tokens)


def _filename_match_key(filename: str) -> str:
    tokens = _filename_tokens(filename)
    meaningful_tokens = [
        token
        for token in tokens
        if token not in SIDE_IMAGE_TOKENS and token not in SIDE_NUMBER_TOKENS
    ]
    return " ".join(meaningful_tokens)


def _filename_tokens(filename: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", Path(filename).stem.lower())
