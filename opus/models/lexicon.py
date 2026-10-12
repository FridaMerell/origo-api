"""Lexical entries used by annotations, their attested forms, and glossaries that collect them."""

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from .planning import TextUnit


class LexicalEntry(models.Model):
    """A word or concept with linguistic attributes."""

    lemma = models.CharField(max_length=255)
    language = models.CharField(max_length=16)
    part_of_speech = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=50, blank=True)
    inflection_data = models.JSONField(default=dict, blank=True)
    # A short gloss shown in a vocabulary quiz; ``definition`` holds the longer explanation.
    translation = models.CharField(max_length=255, blank=True)
    definition = models.TextField(blank=True)
    # Short tags such as "archaic", "formal" or "pejorative"; ``connotation_note`` explains them.
    connotations = models.JSONField(default=list, blank=True)
    connotation_note = models.TextField(blank=True)
    # Null for entries created before entries had owners.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opus_lexical_entries",
    )
    # The users who have marked the word for their vocabulary quizzes. Per user, so that it also
    # works for a word in somebody else's public glossary.
    quiz_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="opus_quiz_entries", blank=True
    )

    class Meta:
        ordering = ["lemma", "language", "id"]
        # The reader looks every word of a page up by its lowercased lemma.
        indexes = [models.Index(Lower("lemma"), name="opus_entry_lemma_lower")]

    def __str__(self):
        return self.lemma


class LexicalSynonym(models.Model):
    """A word with the same or nearly the same meaning as an entry.

    ``text`` is searchable on its own; ``target`` links it to another entry
    when that word is in the lexicon too.
    """

    entry = models.ForeignKey(LexicalEntry, on_delete=models.CASCADE, related_name="synonyms")
    text = models.CharField(max_length=255)
    target = models.ForeignKey(
        LexicalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="synonym_references",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["entry", "id"]

    def __str__(self):
        return f"{self.text} ~ {self.entry}"


class LexicalForm(models.Model):
    """A spelling variant or inflected form tied to an entry's base form.

    A form found in an older text can be linked to a modern lemma even when the
    reader is not sure of it, which ``is_uncertain`` records.
    """

    class Kind(models.TextChoices):
        SPELLING = "spelling", "Spelling variant"
        INFLECTION = "inflection", "Inflected form"

    class Case(models.TextChoices):
        NOMINATIVE = "nominative", "Nominative"
        GENITIVE = "genitive", "Genitive"
        DATIVE = "dative", "Dative"
        ACCUSATIVE = "accusative", "Accusative"
        ABLATIVE = "ablative", "Ablative"
        VOCATIVE = "vocative", "Vocative"
        LOCATIVE = "locative", "Locative"
        INSTRUMENTAL = "instrumental", "Instrumental"

    class Number(models.TextChoices):
        SINGULAR = "singular", "Singular"
        PLURAL = "plural", "Plural"
        DUAL = "dual", "Dual"

    class Person(models.TextChoices):
        FIRST = "1", "First person"
        SECOND = "2", "Second person"
        THIRD = "3", "Third person"

    class Tense(models.TextChoices):
        PRESENT = "present", "Present"
        PAST = "past", "Past"
        IMPERFECT = "imperfect", "Imperfect"
        PERFECT = "perfect", "Perfect"
        PLUPERFECT = "pluperfect", "Pluperfect"
        FUTURE = "future", "Future"
        FUTURE_PERFECT = "future_perfect", "Future perfect"
        AORIST = "aorist", "Aorist"

    class Mood(models.TextChoices):
        INDICATIVE = "indicative", "Indicative"
        SUBJUNCTIVE = "subjunctive", "Subjunctive"
        OPTATIVE = "optative", "Optative"
        IMPERATIVE = "imperative", "Imperative"
        INFINITIVE = "infinitive", "Infinitive"
        PARTICIPLE = "participle", "Participle"
        SUPINE = "supine", "Supine"
        GERUND = "gerund", "Gerund"

    class Voice(models.TextChoices):
        ACTIVE = "active", "Active"
        PASSIVE = "passive", "Passive"
        MIDDLE = "middle", "Middle"

    class Degree(models.TextChoices):
        POSITIVE = "positive", "Positive"
        COMPARATIVE = "comparative", "Comparative"
        SUPERLATIVE = "superlative", "Superlative"

    class Definiteness(models.TextChoices):
        INDEFINITE = "indefinite", "Indefinite"
        DEFINITE = "definite", "Definite"

    # The structured grammatical properties of an inflected form, in the order they are described.
    GRAMMAR_FIELDS = ("grammatical_case", "number", "person", "tense", "mood", "voice", "degree", "definiteness")

    entry = models.ForeignKey(LexicalEntry, on_delete=models.CASCADE, related_name="forms")
    form = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SPELLING)
    # Free text such as "pres. ind. 3 sg."; a note beside the structured properties below.
    inflection = models.CharField(max_length=255, blank=True)
    grammatical_case = models.CharField(max_length=20, choices=Case.choices, blank=True)
    number = models.CharField(max_length=20, choices=Number.choices, blank=True)
    person = models.CharField(max_length=1, choices=Person.choices, blank=True)
    tense = models.CharField(max_length=20, choices=Tense.choices, blank=True)
    mood = models.CharField(max_length=20, choices=Mood.choices, blank=True)
    voice = models.CharField(max_length=20, choices=Voice.choices, blank=True)
    degree = models.CharField(max_length=20, choices=Degree.choices, blank=True)
    definiteness = models.CharField(max_length=20, choices=Definiteness.choices, blank=True)
    is_uncertain = models.BooleanField(default=False)
    # Where the form was found, if anywhere in particular.
    unit = models.ForeignKey(
        TextUnit, on_delete=models.SET_NULL, related_name="lexical_forms", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entry", "form", "id"]
        # The reader looks every word of a page up among the lowercased forms too.
        indexes = [models.Index(Lower("form"), name="opus_form_form_lower")]

    def __str__(self):
        return f"{self.form} → {self.entry}"


class Glossary(models.Model):
    """A word list, public or private to its owner like a work."""

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opus_glossaries"
    )
    is_private = models.BooleanField(default=False)
    entries = models.ManyToManyField(LexicalEntry, related_name="glossaries", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "id"]
        verbose_name_plural = "glossaries"

    def __str__(self):
        return self.title
