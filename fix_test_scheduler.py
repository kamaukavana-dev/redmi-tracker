with open('tests/test_scheduler.py', 'r') as f:
    content = f.read()

content = content.replace("db = SessionLocal()", "db = TestingSessionLocal()")
content = content.replace("async def test_job_runs_with_location_data(self):", "@patch('app.scheduler.SessionLocal', new=TestingSessionLocal)\n    async def test_job_runs_with_location_data(self):")
content = content.replace("async def test_job_handles_telegram_failure(self):", "@patch('app.scheduler.SessionLocal', new=TestingSessionLocal)\n    async def test_job_handles_telegram_failure(self):")

with open('tests/test_scheduler.py', 'w') as f:
    f.write(content)
