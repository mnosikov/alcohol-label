from backend.app.pipeline.review_sampling import sampled_review_score, should_sample_auto_pass


def test_sampled_review_score_is_stable_for_case_and_image() -> None:
    score = sampled_review_score("case-1", "abc123")

    assert score == sampled_review_score("case-1", "abc123")
    assert 0 <= score <= 1


def test_auto_pass_sampling_honors_boundaries() -> None:
    assert should_sample_auto_pass("case-1", "abc123", 0.0) is False
    assert should_sample_auto_pass("case-1", "abc123", 1.0) is True


def test_auto_pass_sampling_uses_hash_bucket() -> None:
    score = sampled_review_score("case-1", "abc123")

    assert should_sample_auto_pass("case-1", "abc123", score + 0.000001) is True
    assert should_sample_auto_pass("case-1", "abc123", max(score - 0.000001, 0)) is False
