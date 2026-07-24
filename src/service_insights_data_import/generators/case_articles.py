"""CaseArticle generator -- Knowledge attach, shared by both tracks.

Per NOTES.md: CaseArticle is a plain junction object (CaseId,
KnowledgeArticleId, ArticleLanguage, ArticleVersionNumber all createable).
Attaches one published Knowledge article to a realistic subset of closed
Cases; org has 68+ Online articles to draw from.
"""

import random


def build_rows(cohort, case_ids_by_seq: dict, knowledge_article_ids: list, rng_seed: int | None = None) -> list:
    if not knowledge_article_ids:
        return []
    rng = random.Random(rng_seed)
    rows = []
    for seq in sorted(cohort.knowledge_seqs):
        case_id = case_ids_by_seq[seq]
        article_id = rng.choice(knowledge_article_ids)
        rows.append({
            "CaseId": case_id,
            "KnowledgeArticleId": article_id,
            "ArticleLanguage": "en_US",
        })
    return rows
