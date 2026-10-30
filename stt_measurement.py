"""Descriptive development measurements for one listened reference and raw STT.

No inference, reference correction, number rewriting, or human judgments.
"""
import math
from score import normalize, score


def measure(reference, hypothesis, *, audio_seconds, wall_seconds, provider_seconds=None, cache_hit=False):
    if (not isinstance(reference, str) or not 1 <= len(reference) <= 1000
            or not normalize(reference) or not isinstance(hypothesis, str) or len(hypothesis) > 2000):
        raise ValueError('Use a nonempty listened reference and bounded raw hypothesis.')
    for value in (audio_seconds, wall_seconds, provider_seconds):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError('Durations must be finite, nonnegative seconds.')
    if audio_seconds is None or not 0 < audio_seconds <= 30 or wall_seconds is None or type(cache_hit) is not bool:
        raise ValueError('Use audio up to 30 seconds and an explicit cache flag.')
    metrics = score([dict(id='observed-dev-clip', reference=reference, hypothesis=hypothesis)])
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    costs = [[i + j if i == 0 or j == 0 else 0 for j in range(len(hyp)+1)] for i in range(len(ref)+1)]
    for i, a in enumerate(ref, 1):
        for j, b in enumerate(hyp, 1):
            costs[i][j] = min(costs[i-1][j-1]+(a != b), costs[i-1][j]+1, costs[i][j-1]+1)
    operations = []
    i, j = len(ref), len(hyp)
    while i or j:
        if i and j and costs[i][j] == costs[i-1][j-1]+(ref[i-1] != hyp[j-1]):
            if ref[i-1] != hyp[j-1]:
                operations.append(dict(kind='substitution', reference=ref[i-1], hypothesis=hyp[j-1]))
            i, j = i-1, j-1
        elif i and costs[i][j] == costs[i-1][j]+1:
            operations.append(dict(kind='deletion', reference=ref[i-1], hypothesis=''))
            i -= 1
        else:
            operations.append(dict(kind='insertion', reference='', hypothesis=hyp[j-1]))
            j -= 1
    operations.reverse()
    assert len(operations) == metrics['word_edit_errors']
    return dict(raw_score=metrics, word_operations=operations,
        substitutions=sum(o['kind']=='substitution' for o in operations),
        deletions=sum(o['kind']=='deletion' for o in operations),
        insertions=sum(o['kind']=='insertion' for o in operations),
        audio_seconds=audio_seconds, wall_seconds=wall_seconds,
        provider_seconds=provider_seconds, wall_rtf=wall_seconds/audio_seconds,
        cache_hit=cache_hit, latency_population='one_observed_development_request',
        critical_semantic_judgments=None, human_task_success=None,
        general_accuracy_claimed=False, reference_or_numbers_rewritten=False)
