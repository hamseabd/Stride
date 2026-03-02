from pydantic import BaseModel, Field
from datetime import datetime
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


class User(BaseModel):
    user_id: str = Field(default_factory=_uuid)
    name: str = ""
    email: str = ""
    phone: str = ""
    onboarded: bool = False
    created_at: str = Field(default_factory=_now)
    timezone: str = "America/New_York"
    checkin_time: str = "09:00"
    evening_time: str = "18:00"
    planning_day: int = 1  # 1=Monday, 7=Sunday


class Project(BaseModel):
    project_id: str = Field(default_factory=_uuid)
    user_id: str
    name: str = ""
    description: str = ""
    target_date: str = ""  # YYYY-MM-DD — when user wants to achieve this goal
    created_at: str = Field(default_factory=_now)


class WorkCycle(BaseModel):
    cycle_id: str = Field(default_factory=_uuid)
    project_id: str
    name: str = ""
    goal: str = ""
    start_date: str = ""
    end_date: str = ""
    status: str = "active"
    created_at: str = Field(default_factory=_now)


class Task(BaseModel):
    task_id: str = Field(default_factory=_uuid)
    cycle_id: str
    title: str
    description: str = ""
    estimate: int = 0        # stored as points: S=2, M=5, L=8, XL=13
    estimate_label: str = "" # S / M / L / XL — what the user sees
    status: str = "todo"
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    status_changed_at: str = Field(default_factory=_now)


class Checkin(BaseModel):
    checkin_id: str = Field(default_factory=_uuid)
    user_id: str
    date: str = Field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d"))
    did: str
    doing: str
    blocked: str = ""
    created_at: str = Field(default_factory=_now)


class Blocker(BaseModel):
    blocker_id: str = Field(default_factory=_uuid)
    task_id: str
    description: str
    resolved: bool = False
    category: str = ""  # external | scope | capacity | process
    created_at: str = Field(default_factory=_now)


class Velocity(BaseModel):
    cycle_id: str
    project_id: str
    planned_points: int = 0
    delivered_points: int = 0
    cycle_name: str = ""
    active_project_count: int = 0
    recorded_at: str = Field(default_factory=_now)


class UserPattern(BaseModel):
    user_id: str
    avg_pace: float = 0.0            # avg delivered_points per cycle
    avg_completion_rate: float = 0.0  # avg delivered/planned ratio
    common_blockers: list = Field(default_factory=list)
    cycle_count: int = 0
    preferred_tone: str = "balanced"  # direct | encouraging | balanced
    updated_at: str = Field(default_factory=_now)


class Habit(BaseModel):
    habit_id: str = Field(default_factory=_uuid)
    user_id: str
    title: str
    frequency: str = "daily"  # daily | weekdays | 3x_week | weekly
    current_streak: int = 0
    longest_streak: int = 0
    last_completed: str = ""  # YYYY-MM-DD
    active: bool = True
    created_at: str = Field(default_factory=_now)
