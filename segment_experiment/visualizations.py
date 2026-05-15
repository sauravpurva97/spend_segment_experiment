from __future__ import annotations

import numpy as np

from .config import RunConfig
from .dimensions import segment_columns


def save_visualizations(outputs: dict, config: RunConfig, logger) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        logger.error("Visualization export skipped | matplotlib unavailable | error=%s", exc)
        return []

    viz_dir = config.output_dir / "visualizations"
    viz_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    weekly_summary = outputs.get("weekly_summary")
    segments = outputs.get("segments")
    campaign_action = outputs.get("experiment_campaigns")

    if weekly_summary is not None and not weekly_summary.empty:
        path = viz_dir / f"{config.file_prefix}_weekly_spend_vs_events.png"
        fig, ax = plt.subplots(figsize=(10, 5))
        x_labels = [str(w.date()) if hasattr(w, "date") else str(w) for w in weekly_summary["week"]]
        width = 0.35
        x = np.arange(len(x_labels))
        ax.bar(x - width / 2, weekly_summary["pct_spend_under"], width, label="% Spend", color="salmon")
        ax.bar(x + width / 2, weekly_summary["pct_events_under"], width, label="% Events", color="steelblue")
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("%")
        ax.set_title("Robust Underperforming Segments: % Spend vs % Goal Events")
        ax.legend()
        fig.tight_layout()
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        logger.info("Visualization written | file=%s", path)
        paths.append(str(path))

    if segments is not None and campaign_action is not None and not segments.empty and not campaign_action.empty:
        seg_cols = segment_columns(config.dimension_names, config.include_country_code)
        top_campaigns = (
            campaign_action.sort_values(["cpa_improvement_pct_realloc", "saved_spend"], ascending=False)
            .head(15)["campaign_id"]
            .tolist()
        )
        viz_segments = segments[segments["campaign_id"].isin(top_campaigns)].copy()

        if not viz_segments.empty:
            path = viz_dir / f"{config.file_prefix}_top_campaign_segment_shares.png"
            n = len(top_campaigns)
            fig, axes = plt.subplots(n, 1, figsize=(12, max(4, 2.8 * n)), sharex=True)
            if n == 1:
                axes = [axes]
            for ax, campaign_id in zip(axes, top_campaigns):
                sub = viz_segments[viz_segments["campaign_id"] == campaign_id].copy()
                sub = sub.sort_values("spend_share_pct", ascending=False).head(8)
                sub = sub.sort_values("spend_share_pct", ascending=True)
                labels = _segment_labels(sub, seg_cols)
                labels = labels + np.where(sub["robust_underperf"], " *", "")
                y = np.arange(len(sub))
                ax.barh(y - 0.18, sub["spend_share_pct"], height=0.35, label="% spend", color="salmon")
                ax.barh(y + 0.18, sub["event_share_pct"].fillna(0), height=0.35, label="% events", color="steelblue")
                ax.set_yticks(y)
                ax.set_yticklabels(labels)
                action_row = campaign_action[campaign_action["campaign_id"] == campaign_id].iloc[0]
                ax.set_title(
                    f"Campaign {campaign_id}: targeted spend={action_row['targeted_spend_pct']:.1f}%, "
                    f"targeted events={action_row['targeted_event_pct']:.1f}%, "
                    f"est. CPA lift={action_row['cpa_improvement_pct_realloc']:.1f}%"
                )
                ax.grid(axis="x", alpha=0.25)
            axes[0].legend(loc="lower right")
            axes[-1].set_xlabel("% of campaign")
            fig.suptitle("Top Campaigns: Segment Spend Share vs Event Share (* = recommended cut)", y=1.002)
            fig.tight_layout()
            fig.savefig(path, dpi=160, bbox_inches="tight")
            plt.close(fig)
            logger.info("Visualization written | file=%s", path)
            paths.append(str(path))

            path = viz_dir / f"{config.file_prefix}_spend_share_vs_event_share_scatter.png"
            scatter = viz_segments.copy()
            fig, ax = plt.subplots(figsize=(9, 7))
            colors = np.where(scatter["robust_underperf"], "crimson", "gray")
            max_spend = scatter["attr_spend"].max()
            sizes = np.clip(scatter["attr_spend"] / max(max_spend, 1e-9) * 500, 20, 500)
            ax.scatter(scatter["spend_share_pct"], scatter["event_share_pct"].fillna(0), s=sizes, c=colors, alpha=0.55)
            max_axis = np.nanmax([scatter["spend_share_pct"].max(), scatter["event_share_pct"].max()])
            ax.plot([0, max_axis], [0, max_axis], linestyle="--", color="black", alpha=0.4, label="event share = spend share")
            ax.set_xlabel("% spend share")
            ax.set_ylabel("% event share")
            ax.set_title("Top Campaign Segments: Spend Share vs Event Share")
            ax.legend()
            ax.grid(alpha=0.25)
            fig.tight_layout()
            fig.savefig(path, dpi=160, bbox_inches="tight")
            plt.close(fig)
            logger.info("Visualization written | file=%s", path)
            paths.append(str(path))

    logger.info("Visualization export complete | count=%s | dir=%s", len(paths), viz_dir)
    return paths


def _segment_labels(df, seg_cols: list[str]):
    if len(seg_cols) == 1:
        return df[seg_cols[0]].astype(str)
    return df[seg_cols].astype(str).agg(" + ".join, axis=1)
