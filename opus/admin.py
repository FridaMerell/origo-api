from origo.admin import site
from opus.models import (
    Alignment,
    AlignmentSet,
    Annotation,
    Bookmark,
    Excerpt,
    LexicalEntry,
    ReadingProgress,
    Shelf,
    SourceFile,
    TextUnit,
    Edition,
    Work,
)


site.register(
    [
        Alignment,
        AlignmentSet,
        Annotation,
        Bookmark,
        Excerpt,
        LexicalEntry,
        ReadingProgress,
        Shelf,
        SourceFile,
        TextUnit,
        Edition,
        Work,
    ]
)
