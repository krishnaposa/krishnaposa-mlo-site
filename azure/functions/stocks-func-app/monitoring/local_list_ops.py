from typing import Dict, List, Tuple
import pandas as pd

def prune_and_replenish_local_list(
    df_all: pd.DataFrame,
    local_list: List[str],
    universe_list: List[str],
    *,
    prune_count: int,
    min_price: float,
    min_strength_z: float,
    max_size: int | None
) -> Tuple[List[str], Dict[str, List[str]]]:
    removed, added = [], []
    if prune_count > 0 and len(local_list) > 0:
        pool = df_all[df_all["ticker"].isin(local_list)].copy()
        pool = pool.sort_values("final_rank", ascending=True)
        to_drop = pool["ticker"].head(prune_count).tolist()
        if to_drop:
            removed = to_drop
            local_list = [t for t in local_list if t not in set(to_drop)]
    candidates = df_all[
        (df_all["ticker"].isin(universe_list)) &
        (~df_all["ticker"].isin(local_list)) &
        (df_all["last_price"] >= min_price) &
        (df_all["strength_score"] >= min_strength_z)
    ].sort_values("final_rank", ascending=False)
    for t in candidates["ticker"].tolist():
        if max_size and len(local_list) >= max_size:
            break
        local_list.append(t)
        added.append(t)
    return local_list, {"added": added, "removed": removed}