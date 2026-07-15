# Database migrations

Run migrations as a one-shot process before API/worker rollout:

    alembic upgrade head

Do not run schema mutation automatically in every application replica. Changes
must follow expand, backfill, then contract across separate releases.
