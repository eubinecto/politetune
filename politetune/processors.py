import itertools
import pandas as pd
from khaiii.khaiii import KhaiiiApi
from typing import Optional, Any, Callable, List
from politetune.fetchers import fetch_abbreviations, fetch_honorifics, fetch_rules, fetch_irregulars


class Tuner:
    """
    a politeness tuner.
    """
    ABBREVIATIONS: dict = fetch_abbreviations()
    HONORIFICS: dict = fetch_honorifics()
    RULES: dict = fetch_rules()
    IRREGULARS: dict = fetch_irregulars()

    def __init__(self):
        self.khaiii = KhaiiiApi()
        # inputs
        self.sent: Optional[str] = None
        self.listener: Optional[str] = None
        self.visibility: Optional[str] = None
        # the output can be anything
        self.out: Any = None
        self.logs: list = list()
        self.history_honorifics: set = set()
        self.history_abbreviations: set = set()
        self.history_irregulars: set = set()

    def __call__(self, sent: str, listener: str, visibility: str) -> str:
        # register inputs
        self.sent = sent
        self.listener = listener
        self.visibility = visibility
        # process each step
        for step in self.steps():
            step()
        # return the final output
        return self.out

    def steps(self) -> List[Callable]:
        return [
            self.clear,
            self.preprocess,
            self.analyze_morphemes,
            self.log,
            self.apply_honorifics,
            self.log,
            self.apply_abbreviations,
            self.log,
            self.apply_irregulars,
            self.log,
            self.postprocess
        ]

    def clear(self):
        self.logs.clear()
        self.history_honorifics.clear()
        self.history_abbreviations.clear()
        self.history_irregulars.clear()

    def log(self):
        self.logs.append(self.out)

    def preprocess(self):
        self.out = self.sent + "." if not self.sent.endswith(".") else self.sent  # for accurate pos-tagging

    def analyze_morphemes(self):
        tokens = self.khaiii.analyze(self.out)
        self.out = tokens

    def apply_honorifics(self):
        politeness = self.RULES[self.listener][self.visibility]['politeness']
        lexicon2morphs = [(token.lex, list(map(str, token.morphs))) for token in self.out]
        out = list()
        for lex, morphs in lexicon2morphs:
            # this is to be used just for matching
            substrings = ["+".join(morphs[i:j]) for i, j in itertools.combinations(range(len(morphs) + 1), 2)]
            if set(substrings) & set(self.HONORIFICS.keys()):  # need to make sure any patterns match joined.
                tuned = "+".join(morphs)
                for pattern in self.HONORIFICS.keys():
                    honorific = self.HONORIFICS[pattern][politeness]
                    tuned = tuned.replace(pattern, honorific)
                    self.history_honorifics.add((pattern, honorific))  # to be used in the explainer
                tuned = "".join([token.split("/")[0] for token in tuned.split("+")])
                out.append(tuned)
            else:
                out.append(lex)
        self.out = " ".join(out)

    def apply_abbreviations(self):
        for key, val in self.ABBREVIATIONS.items():
            if key in self.out:
                self.out = self.out.replace(key, val)
                self.history_abbreviations.add((key, val))

    def apply_irregulars(self):
        for key, val in self.IRREGULARS.items():
            if key in self.out:
                self.out = self.out.replace(key, val)
                self.history_irregulars.add((key, val))

    def postprocess(self):
        self.out = self.out if self.sent.endswith(".") else self.out[:-1]

    @property
    def listeners(self):
        return pd.DataFrame(self.RULES).transpose().index

    @property
    def visibilities(self):
        return pd.DataFrame(self.RULES).transpose().columns


class Explainer:
    """
    This is here to explain each step in tuner. (mainly - apply_honorifics, apply_abbreviations, apply_irregulars).
    It is given a tuner as an input, attempts to explain the latest process.
    """
    def __init__(self, tuner: Tuner):
        self.tuner = tuner

    def __call__(self, *args, **kwargs) -> List[str]:
        # --- step 1 ---
        msg_1 = "### 1️⃣ Determine the level of politeness"
        politeness = self.tuner.RULES[self.tuner.listener][self.tuner.visibility]['politeness']
        politeness = "intimate style (Banmal)" if politeness == 1\
            else "polite style (Banmal)" if politeness == 2\
            else "formal style"
        reason = self.tuner.RULES[self.tuner.listener][self.tuner.visibility]['reason']
        msg_1 += f"\nYou should speak in `{politeness}`."
        msg_1 += f"\n\n Why? {reason}"
        # --- step 2 ---
        msg_2 = f"### 2️⃣ Analyze morphemes"
        analyzed = "".join(["".join(list(map(str, token.morphs))) for token in self.tuner.logs[0]])
        msg_2 += f"\n{self.tuner.sent} → {analyzed}"
        # --- step 3 ---
        msg_3 = f"### 3️⃣ Apply honorifics"
        before = analyzed
        after = self.tuner.logs[1]
        for key, val in self.tuner.history_honorifics:
            before = before.replace(key, f"`{key}`")
            after = after.replace(val, f"`{val}`")
        msg_3 += f"\n{before} → {after}"
        # --- step 4 ---
        msg_4 = "### 4️⃣ Apply abbreviations"
        if len(self.tuner.history_abbreviations) > 0:
            before = self.tuner.logs[1]
            after = self.tuner.logs[2]
            for key, val in self.tuner.history_abbreviations:
                before = before.replace(key, f"`{key}`")
                after = after.replace(val, f"`{val}`")
            msg_4 += f"\n{before} → {after}"
        else:
            msg_4 += "\nNo abbreviation rules were applied."
        # --- step 5 ---
        msg_5 = f"### 5️⃣ Apply irregular conjugations"
        if len(self.tuner.history_irregulars) > 0:
            print(self.tuner.history_irregulars)
            before = self.tuner.logs[2]
            after = self.tuner.logs[3]
            for key, val in self.tuner.history_irregulars:
                before = before.replace(key, f"`{key}`")
                after = after.replace(val, f"`{val}`")
            msg_5 += f"\n{before} → {after}"
        else:
            msg_5 += "\nNo conjugation rules were applied."
        return [
            msg_1, msg_2,
            msg_3, msg_4, msg_5
        ]
