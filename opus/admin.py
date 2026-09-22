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
    LexicalEntry,
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
        LexicalEntry,
        ReadingProgress,
        Shelf,
        SourceFile,
        TextUnit,
        Edition,
        Work,
        WorkContributor,
    ]
)
