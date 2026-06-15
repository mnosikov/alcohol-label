import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from PIL import Image, ImageFilter, ImageStat


@dataclass(frozen=True)
class LocalImageQualityAssessment:
    requires_review: bool
    flags: list[str]
    metrics: dict[str, float]
    rationale: str


QUALITY_FLAG_LABELS = {
    "local_low_contrast": "low contrast",
    "local_blur": "blur or weak edge detail",
    "local_glare": "glare or washed-out bright areas",
    "local_border_crop_or_damage": "possible cropped or damaged border",
    "local_skew": "skew or rotation",
}


def describe_quality_flags(flags: list[str]) -> list[str]:
    return [
        QUALITY_FLAG_LABELS.get(flag, flag.removeprefix("local_").replace("_", " "))
        for flag in flags
    ]


def summarize_quality_flags(flags: list[str]) -> str:
    findings = describe_quality_flags(flags)
    if not findings:
        return "no local quality issues"
    if len(findings) == 1:
        return findings[0]
    if len(findings) == 2:
        return f"{findings[0]} and {findings[1]}"
    return f"{', '.join(findings[:-1])}, and {findings[-1]}"


def _percentile(histogram: list[int], quantile: float) -> int:
    total = sum(histogram)
    target = total * quantile
    seen = 0
    for value, count in enumerate(histogram):
        seen += count
        if seen >= target:
            return value
    return 255


def _edge_orientation_median_deviation(gray: Image.Image) -> float:
    sample = gray.copy()
    sample.thumbnail((256, 256))
    width, height = sample.size
    pixels = sample.tobytes()
    deviations: list[float] = []

    def pixel(x: int, y: int) -> int:
        return pixels[y * width + x]

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            gx = (
                -pixel(x - 1, y - 1)
                + pixel(x + 1, y - 1)
                - 2 * pixel(x - 1, y)
                + 2 * pixel(x + 1, y)
                - pixel(x - 1, y + 1)
                + pixel(x + 1, y + 1)
            )
            gy = (
                -pixel(x - 1, y - 1)
                - 2 * pixel(x, y - 1)
                - pixel(x + 1, y - 1)
                + pixel(x - 1, y + 1)
                + 2 * pixel(x, y + 1)
                + pixel(x + 1, y + 1)
            )
            magnitude = math.hypot(gx, gy)
            if magnitude < 80:
                continue
            edge_angle = (math.degrees(math.atan2(gy, gx)) + 90) % 180
            deviations.append(min(abs(edge_angle), abs(edge_angle - 90), abs(edge_angle - 180)))

    return float(median(deviations)) if deviations else 0.0


def _border_metrics(gray: Image.Image, edge: Image.Image) -> dict[str, float]:
    width, height = gray.size
    border = max(12, int(min(width, height) * 0.06))
    gray_pixels = gray.tobytes()
    edge_pixels = edge.tobytes()
    border_count = 0
    border_edge_count = 0
    bright_border_count = 0

    for y in range(height):
        for x in range(width):
            if not (x < border or x >= width - border or y < border or y >= height - border):
                continue
            border_count += 1
            index = y * width + x
            border_edge_count += edge_pixels[index] >= 35
            bright_border_count += gray_pixels[index] >= 245

    return {
        "border_edge_density": border_edge_count / max(border_count, 1),
        "bright_border_ratio": bright_border_count / max(border_count, 1),
    }


def assess_local_image_quality(image_path: Path) -> LocalImageQualityAssessment:
    try:
        image = Image.open(image_path).convert("RGB")
    except OSError:
        return LocalImageQualityAssessment(
            requires_review=False,
            flags=[],
            metrics={},
            rationale="Local image quality unavailable",
        )
    image.thumbnail((512, 512))
    gray = image.convert("L")
    histogram = gray.histogram()
    total_pixels = gray.width * gray.height
    p10 = _percentile(histogram, 0.10)
    p90 = _percentile(histogram, 0.90)
    span80 = p90 - p10
    stat = ImageStat.Stat(gray)
    luminance_std = float(stat.stddev[0])

    edge = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edge)
    edge_mean = float(edge_stat.mean[0])
    edge_pixels = edge.tobytes()
    edge_ratio = sum(value >= 35 for value in edge_pixels) / max(total_pixels, 1)

    bright_ratio = sum(histogram[245:]) / max(total_pixels, 1)
    border = _border_metrics(gray, edge)
    orientation_median_deviation = _edge_orientation_median_deviation(gray)

    metrics = {
        "luminance_std": round(luminance_std, 3),
        "luminance_span80": float(span80),
        "edge_mean": round(edge_mean, 3),
        "edge_ratio": round(edge_ratio, 5),
        "bright_ratio": round(bright_ratio, 5),
        "bright_border_ratio": round(border["bright_border_ratio"], 5),
        "border_edge_density": round(border["border_edge_density"], 5),
        "orientation_median_deviation": round(orientation_median_deviation, 3),
    }

    flags: list[str] = []
    if span80 < 35 or luminance_std < 18:
        flags.append("local_low_contrast")
    if edge_mean < 14:
        flags.append("local_blur")
    if bright_ratio >= 0.25 or border["bright_border_ratio"] >= 0.10:
        flags.append("local_glare")
    if border["border_edge_density"] >= 0.065:
        flags.append("local_border_crop_or_damage")
    if orientation_median_deviation >= 5.5:
        flags.append("local_skew")

    return LocalImageQualityAssessment(
        requires_review=bool(flags),
        flags=flags,
        metrics=metrics,
        rationale=(
            "Local image quality checks passed"
            if not flags
            else f"Local image quality requires human review: {summarize_quality_flags(flags)}"
        ),
    )
