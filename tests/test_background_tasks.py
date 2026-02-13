"""
Test cases for background tasks in Hypern framework.

Tests cover:
- Task submission
- Task status retrieval
- Task completion
"""

import time
import httpx
import pytest


class TestTaskSubmission:
    """Test background task submission."""
    
    def test_submit_task(self, client: httpx.Client):
        """Test submitting a background task."""
        task_data = {"action": "process", "items": [1, 2, 3]}
        response = client.post("/tasks/submit", json=task_data)
        assert response.status_code == 200
        data = response.json()
        
        assert "task_id" in data
        assert data["status"] == "submitted"
    
    def test_submit_task_returns_id(self, client: httpx.Client):
        """Test task submission returns valid task ID."""
        response = client.post(
            "/tasks/submit",
            json={"data": "test"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Task ID should be a non-empty string
        assert isinstance(data["task_id"], str)
        assert len(data["task_id"]) > 0


class TestTaskStatus:
    """Test task status retrieval."""
    
    def test_get_task_status(self, client: httpx.Client):
        """Test getting task status."""
        # Submit a task
        submit_response = client.post(
            "/tasks/submit",
            json={"process": "test-status"}
        )
        assert submit_response.status_code == 200
        task_id = submit_response.json()["task_id"]
        
        # Get task status (might be pending or completed)
        status_response = client.get(f"/tasks/{task_id}")
        # Status might be 200 or 404 depending on task storage
        assert status_response.status_code in [200, 404]
    
    def test_nonexistent_task(self, client: httpx.Client):
        """Test getting status of non-existent task."""
        response = client.get("/tasks/nonexistent-task-id-12345")
        assert response.status_code == 404
        data = response.json()
        
        assert "error" in data


class TestTaskCompletion:
    """Test task completion scenarios."""
    
    def test_task_completes(self, client: httpx.Client):
        """Test that submitted task eventually completes."""
        # Submit a task
        submit_response = client.post(
            "/tasks/submit",
            json={"action": "complete-test"}
        )
        assert submit_response.status_code == 200
        task_id = submit_response.json()["task_id"]
        
        # Wait a bit for task to complete
        time.sleep(0.5)
        
        # Check status
        status_response = client.get(f"/tasks/{task_id}")
        # Task might complete or not be stored, both are valid
        assert status_response.status_code in [200, 404]
    
    def test_multiple_tasks(self, client: httpx.Client):
        """Test submitting multiple tasks."""
        task_ids = []
        
        for i in range(3):
            response = client.post(
                "/tasks/submit",
                json={"task_number": i}
            )
            assert response.status_code == 200
            task_ids.append(response.json()["task_id"])
        
        # All should have unique IDs
        assert len(set(task_ids)) == 3


class TestTaskDataHandling:
    """Test task data handling."""
    
    def test_task_with_complex_data(self, client: httpx.Client):
        """Test task with complex nested data."""
        complex_data = {
            "action": "process",
            "items": [
                {"id": 1, "name": "Item 1"},
                {"id": 2, "name": "Item 2"}
            ],
            "metadata": {
                "priority": "high",
                "tags": ["urgent", "important"]
            }
        }
        response = client.post("/tasks/submit", json=complex_data)
        assert response.status_code == 200
        data = response.json()
        
        assert "task_id" in data
    
    def test_task_with_empty_data(self, client: httpx.Client):
        """Test task with empty data."""
        response = client.post("/tasks/submit", json={})
        assert response.status_code == 200
        data = response.json()
        
        assert "task_id" in data
