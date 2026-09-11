from sqlalchemy import inspect, text

import rn_live.db as db


def test_claim_review_columns_are_added_to_an_existing_database(tmp_path):
    engine, _ = db.database(f"sqlite:///{tmp_path}/legacy.db")
    try:
        db.Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE analysis_runs DROP COLUMN unreviewed_segment_count"))
            connection.execute(text("ALTER TABLE analysis_runs DROP COLUMN token"))
            connection.execute(text("ALTER TABLE analysis_runs DROP COLUMN lease_until"))
            connection.execute(text("ALTER TABLE analysis_runs DROP COLUMN attempts"))
            connection.execute(text("ALTER TABLE claims DROP COLUMN status"))
            connection.execute(text("ALTER TABLE claims DROP COLUMN revision"))
            connection.execute(text("ALTER TABLE claims DROP COLUMN conversation_relation"))
            connection.execute(text("ALTER TABLE claims DROP COLUMN context_required"))
            connection.execute(text("ALTER TABLE claims DROP COLUMN standalone_text"))
            connection.execute(text("ALTER TABLE claim_segments DROP COLUMN speaker_name"))
            connection.execute(text("ALTER TABLE claim_segments DROP COLUMN relation"))

        initialize = getattr(db, "initialize_database", None)
        assert callable(initialize), "Falta la migración de las tablas de afirmaciones"
        initialize(engine)

        columns = lambda table: {column["name"] for column in inspect(engine).get_columns(table)}
        assert {"unreviewed_segment_count", "token", "lease_until", "attempts"} <= columns("analysis_runs")
        assert {"status", "revision", "conversation_relation", "context_required", "standalone_text"} <= columns("claims")
        assert {"speaker_name", "relation"} <= columns("claim_segments")
    finally:
        engine.dispose()
