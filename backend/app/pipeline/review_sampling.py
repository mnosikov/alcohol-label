import hashlib


def sampled_review_score(case_id: str, image_sha256: str) -> float:
    digest = hashlib.sha256(f"{case_id}:{image_sha256}".encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFFFFFFFFFFFFFF


def should_sample_auto_pass(case_id: str, image_sha256: str, sample_rate: float) -> bool:
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    return sampled_review_score(case_id, image_sha256) < sample_rate
