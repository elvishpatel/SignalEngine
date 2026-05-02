from __future__ import annotations

import pandas as pd


class QualityValidator:
    def validate(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        required = ["symbol", "date", "open", "high", "low", "close", "volume"]
        frame = df.copy()
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"Missing required columns for {source}: {missing}")
        frame = frame.drop_duplicates(subset=["symbol", "date"], keep="first").reset_index(drop=True)
        numeric_columns = ["open", "high", "low", "close", "volume"]
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["quality_score"] = 1.0
        null_mask = frame[numeric_columns].isnull().any(axis=1)
        frame.loc[null_mask, "quality_score"] = 0.5
        zero_volume_mask = frame["volume"].fillna(0) == 0
        bad_close_mask = frame["close"].fillna(0) <= 0
        frame.loc[zero_volume_mask | bad_close_mask, "quality_score"] = 0.0
        volume_mean = frame["volume"].mean()
        volume_std = frame["volume"].std(ddof=0)
        if pd.notna(volume_std) and volume_std > 0:
            frame["volume_zscore"] = (frame["volume"] - volume_mean) / volume_std
            frame.loc[frame["volume_zscore"] > 5, "quality_score"] = 0.3
        else:
            frame["volume_zscore"] = 0.0
        frame["source"] = source
        validated = frame[frame["quality_score"] >= 0.5].copy()
        return validated.drop(columns=["volume_zscore"]).reset_index(drop=True)


def main() -> None:
    sample = pd.DataFrame([
        {"symbol": "SBIN", "date": "2024-01-15", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10000}
    ])
    print(QualityValidator().validate(sample, "demo").to_dict(orient="records"))


if __name__ == "__main__":
    main()
