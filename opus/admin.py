from origo.admin import site
from opus.models import (
    Alignment,
    AlignmentSet,
    Annotation,
    Author,
    AuthorAlias,
    AuthorIdentifier,
    BibliographyEntry,
    Bookmark,
    Excerpt,
    Glossary,
    LexicalEntry,
    LexicalForm,
    ReadingProgress,
    Shelf,
    SourceFile,
    TextUnit,
    Edition,
    Work,
    WorkContributor,
)


site.register(
    [
        Alignment,
        AlignmentSet,
        Annotation,
        Author,
        AuthorAlias,
        AuthorIdentifier,
        BibliographyEntry,
        Bookmark,
        Excerpt,
        Glossary,
        LexicalEntry,
        LexicalForm,
        ReadingProgress,
        Shelf,
        SourceFile,
        TextUnit,
        Edition,
        Work,
        WorkContributor,
    ]
)
