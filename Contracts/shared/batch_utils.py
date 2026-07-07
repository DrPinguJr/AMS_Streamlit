from __future__ import annotations

from io import BytesIO

import pandas as pd


def parse_excel_upload(uploaded_file: object, required_columns: list[str]) -> pd.DataFrame:
    dataframe = pd.read_excel(uploaded_file)
    return normalize_dataframe(dataframe, required_columns)


def parse_tab_separated_paste(text: str, required_columns: list[str]) -> pd.DataFrame:
    dataframe = pd.read_csv(BytesIO(text.encode("utf-8")), sep="\t")
    return normalize_dataframe(dataframe, required_columns)


def normalize_dataframe(data: object, required_columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(data if data is not None else [], columns=required_columns)
    df = df.reindex(columns=required_columns)
    df = df.fillna("").astype(str)
    for column in required_columns:
        df[column] = df[column].str.strip()
    return remove_blank_rows(df, required_columns)


def remove_blank_rows(dataframe: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return dataframe[~(dataframe[columns] == "").all(axis=1)].copy()


def missing_required_columns(dataframe: pd.DataFrame, required_columns: list[str]) -> list[str]:
    return [column for column in required_columns if column not in dataframe.columns]
