"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from decimal import Decimal, ROUND_HALF_UP
import calendar


load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def create_indexes():
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    shift_end: str,
) -> int:
    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    shift_date = punch_in.date()

    # For overnight shifts, an early-morning punch-in
    # belongs to the shift that started the previous day.
    if (
        (end_hour, end_minute) <= (start_hour, start_minute)
        and (punch_in.hour, punch_in.minute) < (end_hour, end_minute)
    ):
        shift_date -= timedelta(days=1)

    shift_start_time = datetime(
        shift_date.year,
        shift_date.month,
        shift_date.day,
        start_hour,
        start_minute,
        tzinfo=IST,
    )

    minutes = int((punch_in - shift_start_time).total_seconds() // 60)

    # Late only when more than 10 minutes after shift start.
    return minutes if minutes > 10 else 0


from decimal import Decimal, ROUND_HALF_UP


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    elapsed_seconds = int((punch_out - punch_in).total_seconds())
    hours = Decimal(elapsed_seconds) / Decimal(3600)

    rounded_hours = hours.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return float(rounded_hours)


def compute_overtime(
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
    date_str: str,
) -> int:
    h_start, m_start = map(int, shift_start.split(":"))
    h_end, m_end = map(int, shift_end.split(":"))

    shift_date = datetime.fromisoformat(date_str).date()

    shift_end_time = datetime(
        shift_date.year,
        shift_date.month,
        shift_date.day,
        h_end,
        m_end,
        tzinfo=IST,
    )

    # Overnight shift: its end falls on the following day.
    if (h_end, m_end) <= (h_start, m_start):
        shift_end_time += timedelta(days=1)

    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=timezone.utc)

    punch_out = punch_out.astimezone(IST)

    elapsed_minutes = int(
        (punch_out - shift_end_time).total_seconds() // 60
    )

    return elapsed_minutes if elapsed_minutes >= 30 else 0



PRESENT = {"PRESENT", "WFH", "ON_DUTY"}


def round_half_up(value, places=2):
    quantizer = Decimal("1").scaleb(-places)
    return float(
        Decimal(str(value)).quantize(
            quantizer,
            rounding=ROUND_HALF_UP
        )
    )


def month_bounds(month):
    try:
        year, month_number = map(int, month.split("-"))
        start = date(year, month_number, 1)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    end = date(
        year,
        month_number,
        calendar.monthrange(year, month_number)[1]
    )

    return start.isoformat(), end.isoformat(), start, end


def working_days(start, end):
    if start > end:
        return 0

    full_weeks, remaining_days = divmod(
        (end - start).days + 1, 7
    )

    days = full_weeks * 5

    for offset in range(remaining_days):
        current_day = (start.weekday() + offset) % 7
        if current_day < 5:
            days += 1

    return days


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str

# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    doc.pop("_id", None)
    return doc




@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page_size must be between 1 and 100")

    q = {}
    if department:
        q["department"] = department

    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)

    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }





from pymongo.errors import DuplicateKeyError


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if body.status not in {"PRESENT", "WFH", "ON_DUTY"}:
        raise HTTPException(
            status_code=422,
            detail="Status must be PRESENT, WFH, or ON_DUTY",
        )

    if body.punched_at is not None:
        try:
            ts = datetime.fromtimestamp(
                body.punched_at / 1000,
                tz=timezone.utc,
            ).astimezone(IST)
        except (ValueError, OverflowError, OSError):
            raise HTTPException(
                status_code=422,
                detail="Invalid punched_at timestamp",
            )
    else:
        ts = datetime.now(IST)

    # Truncate to whole seconds, as required by the assignment.
    ts = ts.replace(microsecond=0)

    start_hour, start_minute = map(int, emp["shift_start"].split(":"))
    end_hour, end_minute = map(int, emp["shift_end"].split(":"))

    attendance_date = ts.date()

    # An early-morning punch-in for an overnight shift
    # belongs to the previous shift-start date.
    if (
        (end_hour, end_minute) <= (start_hour, start_minute)
        and (ts.hour, ts.minute) < (end_hour, end_minute)
    ):
        attendance_date -= timedelta(days=1)

    date_str = attendance_date.isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": date_str,
        "status": body.status,
        "punch_in": ts.astimezone(timezone.utc),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts,
            emp["shift_start"],
            emp["shift_end"],
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        result = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Already punched in for this shift date",
        )


    doc.pop("_id", None)

    # Return punch-in as epoch milliseconds.
    doc["punch_in"] = int(
        doc["punch_in"].replace(tzinfo=timezone.utc).timestamp() * 1000
    )

    return doc



@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be before or equal to date_to",
        )

    allowed_statuses = {
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    }

    if status is not None and status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail="Invalid attendance status",
        )

    query = {}

    if emp_code:
        query["emp_code"] = emp_code

    if date_from or date_to:
        query["date"] = {}
        if date_from:
            query["date"]["$gte"] = date_from.isoformat()
        if date_to:
            query["date"]["$lte"] = date_to.isoformat()

    if status:
        query["status"] = status

    total = db.attendance_logs.count_documents(query)
    skip = (page - 1) * page_size

    cursor = (
        db.attendance_logs.find(query, {"_id": 0})
        .sort("date", -1)
        .skip(skip)
        .limit(page_size)
    )

    items = []

    for doc in cursor:
        for field in ("punch_in", "punch_out"):
            value = doc.get(field)
            if value is not None:
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                doc[field] = int(value.timestamp() * 1000)

        items.append(doc)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if body.punched_at is not None:
        try:
            punched_out = datetime.fromtimestamp(
                body.punched_at / 1000,
                tz=timezone.utc,
            )
        except (ValueError, OverflowError, OSError):
            raise HTTPException(
                status_code=422,
                detail="Invalid punched_at timestamp",
            )
    else:
        punched_out = datetime.now(timezone.utc)

    punched_out = punched_out.replace(microsecond=0)

    
# Find the most recent attendance record whose punch-in
# happened at or before the requested punch-out time.
    record = db.attendance_logs.find_one(
        {
        "emp_code": body.emp_code,
        "punch_in": {"$lte": punched_out},
        },
        sort=[("punch_in", -1)],
        )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found",
        )

    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="Already punched out",
        )

    if record.get("punch_in") is None:
        raise HTTPException(
            status_code=409,
            detail="Attendance record has no punch-in time",
        )

    punch_in_time = record["punch_in"]

    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

    
    elapsed_seconds = (punched_out - punch_in_time).total_seconds()

    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in and within 24 hours",
            )


    work_hours = compute_work_hours(punch_in_time, punched_out)
    overtime_minutes = compute_overtime(
        punched_out,
        emp["shift_start"],
        emp["shift_end"],
        record["date"],
    )
    half_day = work_hours < 4.50

    # Atomic condition: only one concurrent request can set punch_out.
    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": punched_out,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Already punched out",
        )

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated.pop("_id", None)

    for field in ("punch_in", "punch_out"):
        value = updated.get(field)
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            updated[field] = int(value.timestamp() * 1000)

    return updated

@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: date,
    body: RegularizeIn,
):
    from datetime import date as date_type

    if len(body.reason.strip()) < 5 or len(body.reason) > 200:
        raise HTTPException(
            status_code=422,
            detail="reason must contain 5 to 200 characters",
        )

    if not body.regularized_by.strip() or len(body.regularized_by) > 50:
        raise HTTPException(
            status_code=422,
            detail="regularized_by must contain 1 to 50 characters",
        )

    if body.status is not None and body.status not in {
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    }:
        raise HTTPException(status_code=422, detail="Invalid status")

    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date.isoformat(),
    })
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found",
        )

    # Distinguish omitted fields from fields explicitly sent as null.
    supplied = body.model_fields_set
    if ("punch_in" in supplied and body.punch_in is None) or (
        "punch_out" in supplied and body.punch_out is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Supplied punch timestamps must be epoch milliseconds",
        )

    old_status = record["status"]
    new_status = body.status if body.status is not None else old_status

    old_in = record.get("punch_in")
    old_out = record.get("punch_out")

    def as_utc(value):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def from_epoch_ms(value):
        try:
            return datetime.fromtimestamp(
                value / 1000,
                tz=timezone.utc,
            ).replace(microsecond=0)
        except (ValueError, OverflowError, OSError):
            raise HTTPException(
                status_code=422,
                detail="Invalid punch timestamp",
            )

    new_in = (
        from_epoch_ms(body.punch_in)
        if "punch_in" in supplied
        else as_utc(old_in)
    )
    new_out = (
        from_epoch_ms(body.punch_out)
        if "punch_out" in supplied
        else as_utc(old_out)
    )

    if new_status in {"ABSENT", "LEAVE"}:
        if "punch_in" in supplied or "punch_out" in supplied:
            raise HTTPException(
                status_code=422,
                detail="ABSENT and LEAVE cannot be supplied with punch timestamps",
            )
        new_in = None
        new_out = None
    else:
        if new_in is None:
            raise HTTPException(
                status_code=422,
                detail="Presence status requires a punch-in time",
            )

        # Validate the IST attendance date, including overnight shifts.
        local_in = new_in.astimezone(IST)
        sh, sm = map(int, emp["shift_start"].split(":"))
        eh, em = map(int, emp["shift_end"].split(":"))

        expected_date = local_in.date()
        if (
            (eh, em) <= (sh, sm)
            and (local_in.hour, local_in.minute) < (eh, em)
        ):
            expected_date -= timedelta(days=1)

        if expected_date.isoformat() != date.isoformat():
            raise HTTPException(
                status_code=422,
                detail="punch_in must belong to the record's attendance date",
            )

        if new_out is not None:
            elapsed = (new_out - new_in).total_seconds()
            if elapsed <= 0 or elapsed > 24 * 60 * 60:
                raise HTTPException(
                    status_code=422,
                    detail="punch_out must be after punch_in and within 24 hours",
                )

    if new_status in {"ABSENT", "LEAVE"}:
        late_minutes = 0
        work_hours = None
        overtime_minutes = 0
        half_day = False
    else:
        late_minutes = compute_late_minutes(
            new_in.astimezone(IST),
            emp["shift_start"],
            emp["shift_end"],
        )

        if new_out is None:
            work_hours = None
            overtime_minutes = 0
            half_day = False
        else:
            work_hours = compute_work_hours(new_in, new_out)
            overtime_minutes = compute_overtime(
                new_out,
                emp["shift_start"],
                emp["shift_end"],
                record["date"],
            )
            half_day = work_hours < 4.50

    old_values = {
        "status": old_status,
        "punch_in": as_utc(old_in),
        "punch_out": as_utc(old_out),
        "work_hours": record.get("work_hours"),
        "late_minutes": record.get("late_minutes", 0),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": record.get("half_day", False),
    }

    new_values = {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    def comparable(value):
        if isinstance(value, datetime):
            return int(value.timestamp() * 1000)
        return value

    changes = {}
    for field, new_value in new_values.items():
        old_value = old_values[field]
        if comparable(old_value) != comparable(new_value):
            if field in {"punch_in", "punch_out"}:
                old_value = (
                    int(old_value.timestamp() * 1000)
                    if old_value is not None else None
                )
                new_value = (
                    int(new_value.timestamp() * 1000)
                    if new_value is not None else None
                )
            changes[field] = {"from": old_value, "to": new_value}

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="The request does not change the attendance record",
        )

    history_entry = {
        "at": int(datetime.now(timezone.utc).timestamp() * 1000),
        "by": body.regularized_by,
        "reason": body.reason.strip(),
        "changes": changes,
    }

    # Optimistic concurrency: if another edit or punch-out changes the
    # record after our read, this update will not match.
    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "status": old_status,
            "punch_in": old_in,
            "punch_out": old_out,
            "history": record.get("history", []),
        },
        {
            "$set": {
                "status": new_status,
                "punch_in": new_in,
                "punch_out": new_out,
                "work_hours": work_hours,
                "late_minutes": late_minutes,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            },
            "$push": {"history": history_entry},
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance changed concurrently; retry the correction",
        )

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated["id"] = str(updated.pop("_id"))

    # The API contract represents punch timestamps and history.at in epoch ms.
    for field in ("punch_in", "punch_out"):
        value = updated.get(field)
        updated[field] = (
            int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)
            if value is not None and value.tzinfo is None
            else int(value.timestamp() * 1000) if value is not None else None
        )

    for entry in updated.get("history", []):
        if isinstance(entry.get("at"), datetime):
            entry["at"] = int(entry["at"].timestamp() * 1000)

    return updated


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: str = Query(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    )
):
    start_s, end_s, start, end = month_bounds(month)

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    joined_value = employee["joined_on"]
    joined = (
        date.fromisoformat(joined_value)
        if isinstance(joined_value, str)
        else joined_value.date()
        if isinstance(joined_value, datetime)
        else joined_value
    )

    effective_start = max(start, joined)
    days = (
        working_days(effective_start, end)
        if effective_start <= end
        else 0
    )

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": start_s,
                    "$lte": end_s
                }
            }
        },
        {
            "$set": {
                "dow": {
                    "$dayOfWeek": {
                        "$dateFromString": {
                            "dateString": "$date"
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": None,

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$status", list(PRESENT)]},
                                    {"$gte": ["$date", effective_start.isoformat()]},
                                    {"$gte": ["$dow", 2]},
                                    {"$lte": ["$dow", 6]}
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },

                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },

                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },

                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }
            }
        }
    ]

    rows = list(db.attendance_logs.aggregate(pipeline))
    stats = rows[0] if rows else {}

    present_days = stats.get("present_days", 0)

    attendance_pct = (
        round_half_up(present_days / days * 100, 4)
        if days > 0
        else None
    )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": days,
        "present_days": present_days,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get(
            "total_overtime_minutes", 0
        ),
        "attendance_pct": attendance_pct
    }


@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    ),
    department: Optional[str] = None
):
    start_s, end_s, _, _ = month_bounds(month)

    # Include employees who joined on or before the month's end.
    employee_match = {"joined_on": {"$lte": end_s}}

    if department:
        employee_match["department"] = department

    pipeline = [
        {
            "$match": employee_match
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$code"]},
                                    {"$gte": ["$date", start_s]},
                                    {"$lte": ["$date", end_s]}
                                ]
                            }
                        }
                    },
                    {
                        "$project": {
                            "date": 1,
                            "status": 1,
                            "half_day": 1,
                            "work_hours": 1,
                            "late_minutes": 1,
                            "overtime_minutes": 1
                        }
                    }
                ],
                "as": "logs"
            }
        },
        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$set": {
                "dow": {
                    "$cond": [
                        {"$ifNull": ["$logs.date", False]},
                        {
                            "$dayOfWeek": {
                                "$dateFromString": {
                                    "dateString": "$logs.date"
                                }
                            }
                        },
                        None
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": "$department",
                "employee_codes": {"$addToSet": "$emp_code"},

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$logs.status", list(PRESENT)]},
                                    {"$gte": ["$dow", 2]},
                                    {"$lte": ["$dow", 6]}
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },

                "avg_work_hours": {
                    "$avg": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$logs.status", list(PRESENT)]},
                                    {"$ne": ["$logs.work_hours", None]}
                                ]
                            },
                            "$logs.work_hours",
                            None
                        ]
                    }
                },

                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$logs.late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$logs.late_minutes", 0]}
                },

                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },

                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": {"$size": "$employee_codes"},
                "present_days": 1,
                "avg_work_hours": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1
            }
        },
        {
            "$sort": {"department": 1}
        }
    ]

    items = list(db.employees.aggregate(pipeline))

    for item in items:
        item["present_days"] = round_half_up(
            item["present_days"], 2
        )

        if item["avg_work_hours"] is not None:
            item["avg_work_hours"] = round_half_up(
                item["avg_work_hours"], 2
            )

    return {
        "month": month,
        "items": items
    }



@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    ),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None
):
    start_s, end_s, _, _ = month_bounds(month)

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": start_s,
                    "$lte": end_s
                },
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": "$late_minutes"
                },
                "late_count": {"$sum": 1}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department:
        pipeline.append({
            "$match": {
                "employee.department": department
            }
        })

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {
                    "total_late_minutes": -1
                },
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {
            "$match": {
                "rank": {"$lte": limit}
            }
        },
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ])

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items
    }



@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
):
    if to_date < from_date:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'",
        )

    if (to_date - from_date).days > 91:
        raise HTTPException(
            status_code=422,
            detail="Date range must not exceed 92 days",
        )

    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(
            status_code=404,
            detail="Department not found",
        )

    start_s = from_date.isoformat()
    end_s = to_date.isoformat()

    pipeline = [
        {
            "$match": {
                "date": {"$gte": start_s, "$lte": end_s}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {
            "$group": {
                "_id": "$date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", list(PRESENT)]},
                            {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                },
            }
        },
        {"$sort": {"_id": 1}},
    ]

    daily = {
        item["_id"]: item
        for item in db.attendance_logs.aggregate(pipeline)
    }

    # Build one result per calendar day, including days without logs.
    items = []
    current = from_date
    rates = []

    while current <= to_date:
        day_s = current.isoformat()
        weekday = current.weekday() < 5

        headcount = db.employees.count_documents({
            "department": department,
            "joined_on": {"$lte": day_s},
        })

        record = daily.get(day_s, {})
        present_count = record.get("present_count", 0)
        late_count = record.get("late_count", 0)

        if weekday and headcount > 0:
            rate = round_half_up(present_count / headcount, 4)
        else:
            rate = None

        rates.append(rate)
        recent_rates = [r for r in rates[-7:] if r is not None]
        moving_avg = (
            round_half_up(sum(recent_rates) / len(recent_rates), 4)
            if recent_rates else None
        )

        items.append({
            "date": day_s,
            "is_working_day": weekday,
            "headcount": headcount,
            "present_count": present_count,
            "late_count": late_count,
            "attendance_rate": rate,
            "moving_avg_7d": moving_avg,
        })

        current += timedelta(days=1)

    return {
        "department": department,
        "from": start_s,
        "to": end_s,
        "items": items,
    }



@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: str):
    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }

    if endpoint not in allowed:
        raise HTTPException(
            status_code=422,
            detail="Unsupported endpoint name",
        )

    if endpoint == "attendance_list":
        command = {
            "find": "attendance_logs",
            "filter": {},
            "projection": {"_id": 0},
            "sort": {"date": -1},
        }
    else:
        raise HTTPException(
            status_code=501,
            detail=f"Explain implementation pending for {endpoint}",
        )

    result = db.command({
        "explain": command,
        "verbosity": "executionStats",
    })

    return result


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
