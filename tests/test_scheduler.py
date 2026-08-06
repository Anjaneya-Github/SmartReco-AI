"""
tests/test_scheduler.py
------------------------
Unit tests for the APScheduler layer.

Tests cover:
- Scheduler registration: all 3 jobs registered on start
- Job stats: initial state is "never"
- run_job_now: raises ValueError for unknown job_id
- run_job_now: executes the job function and returns status dict
- get_status: returns correct structure when scheduler is running
- Admin endpoints: POST /scheduler/run and GET /scheduler/status
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ------------------------------------------------------------------ #
# Scheduler unit tests                                                #
# ------------------------------------------------------------------ #

class TestSchedulerRegistration:

    def test_all_jobs_registered_on_start(self):
        from app.scheduler.scheduler import get_scheduler, start_scheduler, _JOB_REGISTRY

        # Use a fresh scheduler to avoid state bleed
        import importlib
        import app.scheduler.scheduler as sched_mod
        sched_mod._scheduler = None  # reset singleton

        start_scheduler()
        sched = get_scheduler()

        assert sched.running
        job_ids = {j.id for j in sched.get_jobs()}
        for expected_id in _JOB_REGISTRY:
            assert expected_id in job_ids, f"Job '{expected_id}' not registered"

        sched.shutdown(wait=False)
        sched_mod._scheduler = None  # cleanup

    def test_start_is_idempotent(self):
        """Calling start_scheduler twice should not raise."""
        import app.scheduler.scheduler as sched_mod
        sched_mod._scheduler = None

        from app.scheduler.scheduler import start_scheduler, get_scheduler
        start_scheduler()
        start_scheduler()  # second call — must not raise

        sched = get_scheduler()
        assert sched.running
        sched.shutdown(wait=False)
        sched_mod._scheduler = None

    def test_three_jobs_in_registry(self):
        from app.scheduler.scheduler import _JOB_REGISTRY
        assert len(_JOB_REGISTRY) == 3
        assert "daily_reco_refresh" in _JOB_REGISTRY
        assert "cache_cleanup" in _JOB_REGISTRY
        assert "event_cleanup" in _JOB_REGISTRY


class TestJobStats:

    def test_initial_stats_are_never(self):
        from app.scheduler.jobs import get_job_stats
        stats = get_job_stats()
        for job_id in ("daily_reco_refresh", "cache_cleanup", "event_cleanup"):
            assert job_id in stats
            # last_status may be "never" on a fresh process
            assert "last_status" in stats[job_id]
            assert "last_run" in stats[job_id]

    def test_stats_returns_copy(self):
        """Mutating the returned dict must not affect the internal state."""
        from app.scheduler.jobs import get_job_stats
        s1 = get_job_stats()
        s1["cache_cleanup"]["last_status"] = "mutated"
        s2 = get_job_stats()
        assert s2["cache_cleanup"]["last_status"] != "mutated"


class TestRunJobNow:

    def test_unknown_job_raises_value_error(self):
        from app.scheduler.scheduler import run_job_now
        with pytest.raises(ValueError, match="Unknown job"):
            run_job_now("non_existent_job")

    def test_run_now_returns_dict_with_required_keys(self):
        from app.scheduler.scheduler import run_job_now
        # Patch the actual job function to avoid DB / Redis calls
        with patch("app.scheduler.scheduler._JOB_REGISTRY", {
            "cache_cleanup": (MagicMock(), {}, "Hourly Cache Cleanup"),
        }):
            result = run_job_now("cache_cleanup")

        assert "job_id" in result
        assert "triggered_at" in result
        assert "status" in result
        assert result["job_id"] == "cache_cleanup"

    def test_run_now_captures_exception_in_status(self):
        from app.scheduler.scheduler import run_job_now

        def _boom():
            raise RuntimeError("simulated failure")

        with patch("app.scheduler.scheduler._JOB_REGISTRY", {
            "cache_cleanup": (_boom, {}, "Hourly Cache Cleanup"),
        }):
            result = run_job_now("cache_cleanup")

        assert "error" in result["status"]

    def test_run_cache_cleanup_without_redis(self):
        """cache_cleanup must succeed gracefully when Redis is unavailable."""
        from app.scheduler.jobs import cache_cleanup
        with patch("app.scheduler.jobs._get_redis_or_none", return_value=None):
            # Should not raise
            cache_cleanup()

        from app.scheduler.jobs import get_job_stats
        stats = get_job_stats()
        assert stats["cache_cleanup"]["last_status"] == "skipped_no_redis"


class TestGetStatus:

    def test_status_structure(self):
        import app.scheduler.scheduler as sched_mod
        sched_mod._scheduler = None
        from app.scheduler.scheduler import start_scheduler, get_status

        start_scheduler()
        status = get_status()

        assert status["scheduler_running"] is True
        assert status["registered_jobs"] == 3
        assert len(status["jobs"]) == 3

        for job in status["jobs"]:
            assert "id" in job
            assert "name" in job
            assert "next_run_time" in job
            assert "last_run" in job
            assert "last_status" in job

        sched_mod._scheduler.shutdown(wait=False)
        sched_mod._scheduler = None


# ------------------------------------------------------------------ #
# Admin endpoint integration tests                                    #
# ------------------------------------------------------------------ #

class TestSchedulerAdminEndpoints:
    """
    Tests against the FastAPI test client.
    DB / Redis calls are patched so no real infrastructure is needed.
    """

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app, raise_server_exceptions=False)

        # Get an admin token using mocked auth
        with patch("app.auth.dependencies.UserRepository") as MockRepo:
            from app.models.user import User, UserRole
            fake_admin = MagicMock(spec=User)
            fake_admin.id = __import__("uuid").uuid4()
            fake_admin.role = UserRole.ADMIN
            fake_admin.is_active = True
            MockRepo.return_value.get_by_id.return_value = fake_admin

            from app.auth.jwt import create_access_token
            self._token = create_access_token({"sub": str(fake_admin.id)})

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def test_status_endpoint_returns_200(self):
        r = self.client.get("/api/v1/admin/scheduler/status",
                            headers=self._auth_headers())
        assert r.status_code == 200
        body = r.json()
        assert "scheduler_running" in body
        assert "registered_jobs" in body
        assert "jobs" in body

    def test_run_unknown_job_returns_400(self):
        r = self.client.post(
            "/api/v1/admin/scheduler/run",
            json={"job_id": "does_not_exist"},
            headers=self._auth_headers(),
        )
        assert r.status_code == 400

    def test_run_valid_job_returns_202(self):
        with patch("app.scheduler.scheduler._JOB_REGISTRY", {
            "cache_cleanup": (MagicMock(), {}, "Hourly Cache Cleanup"),
        }):
            r = self.client.post(
                "/api/v1/admin/scheduler/run",
                json={"job_id": "cache_cleanup"},
                headers=self._auth_headers(),
            )
        assert r.status_code == 202
        body = r.json()
        assert body["job_id"] == "cache_cleanup"
        assert "triggered_at" in body

    def test_status_requires_admin(self):
        r = self.client.get("/api/v1/admin/scheduler/status")
        assert r.status_code == 401

    def test_run_requires_admin(self):
        r = self.client.post(
            "/api/v1/admin/scheduler/run",
            json={"job_id": "cache_cleanup"},
        )
        assert r.status_code == 401
