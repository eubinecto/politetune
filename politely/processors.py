import os
import re
import requests  # noqa
import pandas as pd  # noqa
from khaiii.khaiii import KhaiiiApi
from typing import Any
from politely.fetchers import fetch_abbreviations, fetch_honorifics, fetch_rules, fetch_irregulars
from politely.errors import EFNotIncludedError, EFNotSupportedError


class Styler:
    """
    The Korean Politeness Styler
    """
    RULES: dict = fetch_rules()
    HONORIFICS: dict = fetch_honorifics()
    ABBREVIATIONS: dict = fetch_abbreviations()
    IRREGULARS: dict = fetch_irregulars()

    def __init__(self):
        self.khaiii = KhaiiiApi()
        self.args: dict = dict()
        self.out: Any = None
        # --- histories --- #
        self.logs: list = list()
        self.history_conjugations: set = set()
        self.history_abbreviations: set = set()
        self.history_irregulars: set = set()

    def __call__(self, sent: str, listener: str, environ: str) -> str:
        # process with a chain-of-responsibility
        self.args.update(locals())
        self.clear() \
            .preprocess() \
            .analyze() \
            .check() \
            .log() \
            .conjugate() \
            .log() \
            .abbreviate() \
            .log() \
            .apply_irregulars() \
            .log()
        return self.out

    # ---- methods for steps --- #
    def clear(self):
        self.logs.clear()
        self.history_conjugations.clear()
        self.history_abbreviations.clear()
        self.history_irregulars.clear()
        return self

    def log(self):
        self.logs.append(self.out)
        return self

    def preprocess(self):
        self.out = self.args['sent'].strip()  # khaiii model is sensitive to empty spaces, so we should get rid of it.
        if not self.out.endswith("?") and not self.out.endswith("!"):
            self.out = self.out + "." if not self.out.endswith(".") else self.out  # for accurate pos-tagging
        return self

    def analyze(self):
        tokens = self.khaiii.analyze(self.out)
        self.out = tokens
        return self

    def check(self):
        """
        Check if your assumption holds. Raises an error if any of them does not hold.
        """
        efs = [
            "+".join(map(str, token.morphs))
            for token in self.out
            if "EF" in "+".join(map(str, token.morphs))
        ]
        # assumption 1: the sentence must include more than 1 EF's
        if not efs:
            raise EFNotIncludedError("|".join(["+".join(map(str, token.morphs)) for token in self.out]))
        # assumption 2: all EF's should be supported by KPS.
        for ef in efs:
            for pattern in self.HONORIFICS.keys():
                if self.matched(pattern, ef):
                    break
            else:
                raise EFNotSupportedError(ef)
        return self

    def conjugate(self):
        politeness = self.RULES[self.args['listener']][self.args['environ']]['politeness']
        lex2morphs = [(token.lex, list(map(str, token.morphs))) for token in self.out]
        out = list()
        for lex, morphs in lex2morphs:
            tuned = "+".join(morphs)
            for pattern in self.HONORIFICS.keys():
                if self.matched(pattern, tuned):
                    honorific = self.HONORIFICS[pattern][politeness]
                    tuned = tuned.replace(pattern, honorific)
                    self.history_conjugations.add((pattern, honorific))
            # if something has changed, then go for it, but otherwise just use the lex.
            before = "".join([morph.split("/")[0] for morph in morphs])
            after = "".join([morph.split("/")[0] for morph in tuned.split("+")])
            if before != after:
                out.append(after)
            else:
                out.append(lex)
        self.out = " ".join(out)
        return self

    def abbreviate(self):
        for key, val in self.ABBREVIATIONS.items():
            if key in self.out:
                self.out = self.out.replace(key, val)
                self.history_abbreviations.add((key, val))
        return self

    def apply_irregulars(self):
        for key, val in self.IRREGULARS.items():
            if key in self.out:
                self.out = self.out.replace(key, val)
                self.history_irregulars.add((key, val))
        return self

    # --- accessing options --- #
    @property
    def listeners(self):
        return pd.DataFrame(self.RULES).transpose().index

    @property
    def environs(self):
        return pd.DataFrame(self.RULES).transpose().columns

    # --- supporting methods --- #
    @staticmethod
    def matched(pattern: str, string: str) -> bool:
        return True if re.match(f"(^|.*\\+){re.escape(pattern)}(\\+.*|$)", string) else False


class Translator:
    def __call__(self, sent: str) -> str:
        url = "https://openapi.naver.com/v1/papago/n2mt"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Naver-Client-Id": os.environ['NAVER_CLIENT_ID'],
            "X-Naver-Client-Secret": os.environ['NAVER_CLIENT_SECRET']
        }
        data = {
            "source": "en",
            "target": "ko",
            "text": sent
        }
        r = requests.post(url, headers=headers, data=data)
        r.raise_for_status()
        return r.json()['message']['result']['translatedText']


class Explainer:
    """
    This is here to explain each step in tuner. (mainly - apply_honorifics, apply_abbreviations, apply_irregulars).
    It is given a tuner as an input, attempts to explain the latest process.
    """

    def __init__(self, tuner: Styler):
        self.styler = tuner

    def __call__(self, column):
        # CSS to inject contained in a string
        hide_table_row_index = """
                    <style>
                    tbody th {display:none}
                    .blank {display:none}
                    </style>
                    """

        # Inject CSS with Markdown
        column.markdown(hide_table_row_index, unsafe_allow_html=True)
        # --- step 1 ---
        msg_1 = "### 1️⃣ Politeness"
        case = self.styler.RULES[self.styler.args['listener']][self.styler.args['environ']]
        politeness = case['politeness']
        politeness = "casual style (-어)" if politeness == 1 \
            else "polite style (-어요)" if politeness == 2 \
            else "formal style (-습니다)"
        reason = case['reason']
        msg_1 += f"\nYou should speak in a `{politeness}` to your `{self.styler.args['listener']}`" \
                 f" when you are in a `{self.styler.args['environ']}` environment."
        msg_1 += f"\n\n Why so? {reason}"
        column.markdown(msg_1)
        # --- step 2 ---
        msg_2 = f"### 2️⃣ Morphemes"
        before = self.styler.args['sent'].split(" ")
        after = ["".join(list(map(str, token.morphs))) for token in self.styler.logs[0]]
        df = pd.DataFrame(zip(before, after), columns=['before', 'after'])
        column.markdown(msg_2)
        column.markdown(df.to_markdown(index=False))
        # --- step 3 ---
        msg_3 = f"### 3️⃣ Honorifics"
        before = " ".join(["".join(list(map(str, token.morphs))) for token in self.styler.logs[0]])
        after = self.styler.logs[1]
        for key, val in self.styler.history_conjugations:
            before = before.replace(key, f"`{key}`")
            after = after.replace(val, f"`{val}`")
        df = pd.DataFrame(zip(before.split(" "), after.split(" ")), columns=['before', 'after'])
        column.markdown(msg_3)
        column.markdown(df.to_markdown(index=False))
        # # --- step 4 ---
        msg_4 = "### 4️⃣ Abbreviations"
        if len(self.styler.history_abbreviations) > 0:
            before = self.styler.logs[1]
            after = self.styler.logs[2]
            for key, val in self.styler.history_abbreviations:  # noqa
                before = before.replace(key, f"`{key}`")
                after = after.replace(val, f"`{val}`")
            column.markdown(msg_4)
            df = pd.DataFrame(zip(before.split(" "), after.split(" ")), columns=['before', 'after'])
            column.markdown(df.to_markdown(index=False))
        else:
            msg_4 += "\nNo abbreviation rules to be applied."
            column.markdown(msg_4)
        # # --- step 5 ---
        msg_5 = f"### 5️⃣ Conjugations"
        if len(self.styler.history_irregulars) > 0:
            before = self.styler.logs[2]
            after = self.styler.logs[3]
            for key, val in self.styler.history_irregulars:  # noqa
                before = before.replace(key, f"`{key}`")
                after = after.replace(val, f"`{val}`")
            column.markdown(msg_5)
            df = pd.DataFrame(zip(before.split(" "), after.split(" ")), columns=['before', 'after'])
            column.markdown(df.to_markdown(index=False))
        else:
            msg_5 += "\nNo conjugation rules to be applied."
            column.markdown(msg_5)
