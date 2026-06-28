import pandas as pd


REQUIRED_COLUMNS = [
    "contact_name",
    "work_email"
]

OPTIONAL_COLUMNS = [
    "job_title",
    "company_name",
    "mobile",
    "industry",
    "sub_industry"
]


def load_csv(uploaded_file):

    df = pd.read_csv(uploaded_file)

    # Normalize Column Names
    df.columns = [
        col.strip().lower()
        for col in df.columns
    ]

    # Validate Required Columns
    missing_columns = [
        column
        for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:
        raise Exception(
            f"Missing Required Columns: "
            f"{missing_columns}"
        )

    # Auto-fill Optional Columns
    for column in OPTIONAL_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    return df
