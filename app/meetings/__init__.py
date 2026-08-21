"""Meeting and round views, and the bridge between the ORM and the engine.

Deliberately empty of imports. `scoring_bridge` pulls in most of the model
layer, and a package initialiser that imports it would make `from app.meetings
import x` drag the whole thing in wherever it appears — including inside
`app/models/`, which is how a circular import starts.
"""
