"""Opus persistence models, organised by domain."""

from .alignment import (
    Alignment,
    AlignmentGap,
    AlignmentGroup,
    AlignmentMember,
    AlignmentSet,
    AlignmentSpan,
    AlignmentVersion,
)
from .annotations import Annotation
from .bibliography import BibliographyEntry
from .documents import Bookmark, Excerpt, ReadingProgress
from .lexicon import Glossary, LexicalEntry
from .people import Author, AuthorAlias, AuthorIdentifier, WorkContributor
from .planning import Edition, Shelf, SourceFile, TextUnit, Work

__all__ = [
    "Alignment",
    "AlignmentGap",
    "AlignmentGroup",
    "AlignmentMember",
    "AlignmentSet",
    "AlignmentSpan",
    "AlignmentVersion",
    "Annotation",
    "Author",
    "AuthorAlias",
    "AuthorIdentifier",
    "BibliographyEntry",
    "Bookmark",
    "Excerpt",
    "Glossary",
    "LexicalEntry",
    "ReadingProgress",
    "Shelf",
    "SourceFile",
    "TextUnit",
    "Edition",
    "Work",
    "WorkContributor",
]
