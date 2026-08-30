"""Tests for Ingestion Feeds (NSE Bhavcopy, India VIX, AMFI NAVs, RBI FX)."""

import datetime
import io
import pandas as pd
import pytest

from src.ingestion.amfi_feed import AMFINAVFeed
from src.ingestion.nse_feed import NSEBhavcopyFeed
from src.ingestion.rbi_feed import RBIFXFeed
from src.ingestion.vix_feed import IndiaVIXFeed


def test_nse_bhavcopy_schema_standardization():
    feed = NSEBhavcopyFeed()
    raw_csv = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN\n"
        "RELIANCE,EQ,2500.0,2550.0,2490.0,2540.0,2540.0,2500.0,1500000,380000.0,01-JAN-2024,45000,INE002A01018\n"
        "TCS,EQ,3800.0,3850.0,3780.0,3820.0,3820.0,3790.0,800000,305000.0,01-JAN-2024,32000,INE467B01029\n"
    ).encode("utf-8")

    df = feed._parse_raw_payload(raw_csv, datetime.date(2024, 1, 1))
    assert len(df) == 2
    assert "trade_date" in df.columns
    assert "symbol" in df.columns
    assert "close" in df.columns
    assert "volume" in df.columns
    assert df["symbol"].tolist() == ["RELIANCE", "TCS"]
    assert df["close"].iloc[0] == 2540.0


def test_vix_feed_parsing():
    feed = IndiaVIXFeed()
    raw_csv = (
        "Date,Open,High,Low,Close,Prev. Close,Change,% Change\n"
        "01-Jan-2024,14.50,15.20,14.10,14.80,14.50,0.30,2.07\n"
    ).encode("utf-8")

    df = feed._parse_raw_payload(raw_csv)
    assert len(df) == 1
    assert df["close"].iloc[0] == 14.80
    assert df["change"].iloc[0] == 0.30


def test_amfi_nav_feed_parsing():
    feed = AMFINAVFeed()
    raw_text = (
        "Open Ended Schemes (Equity Scheme - Large Cap Fund)\n"
        "HDFC Mutual Fund\n"
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
        "119042;INF179K01BE2;INF179K01BF9;HDFC Top 100 Fund - Growth;850.25;01-Jan-2024\n"
    ).encode("utf-8")

    df = feed._parse_raw_payload(raw_text)
    assert len(df) == 1
    assert df["scheme_code"].iloc[0] == "119042"
    assert df["nav"].iloc[0] == 850.25
    assert "HDFC" in df["fund_house"].iloc[0]


def test_rbi_fx_feed_parsing():
    feed = RBIFXFeed()
    raw_json = b'[{"currency": "USD", "rate": 83.15}, {"currency": "EUR", "rate": 91.20}]'
    df = feed._parse_raw_payload(raw_json, datetime.date(2024, 1, 1))
    assert len(df) == 2
    assert "USD" in df["currency"].values
    assert df[df["currency"] == "USD"]["rate"].iloc[0] == 83.15
