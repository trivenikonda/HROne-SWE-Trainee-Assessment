# DECISIONS.md

## 1. Indexes

I created a unique index on `employees.emp_code` to prevent duplicate employee codes. I also created a unique compound index on `attendance_logs.emp_code` and `attendance_logs.date` to prevent multiple attendance records for the same employee on the same date. I would consider an additional index on `date` for attendance queries sorted by date, after checking the query plan and write overhead.

## 2. Punch-in race

If two identical punch-in requests arrive together, both may pass an initial existence check. The unique compound index prevents both records from being inserted. The request that encounters a duplicate-key error should return a conflict response rather than an internal server error.

## 3. Ties

The leaderboard's result depends on its sorting and limit logic. A secondary sort, such as employee code, provides deterministic results. If all employees tied at the cutoff must be returned, the code must explicitly include those ties.

## 4. Headcount

Department headcount should be calculated from employee records, not only attendance logs. This includes employees who have no attendance records.

## 5. Scaling

For 100 times more data, I would optimize analytics using MongoDB aggregation pipelines, review query execution plans, and add indexes based on frequently used filters and sorts.