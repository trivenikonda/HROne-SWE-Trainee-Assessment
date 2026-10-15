# REVIEW.md

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | Database indexes | Without a unique employee-code index, duplicate employee codes may be stored. | Create two employees with the same employee code. | Added a unique index on `employees.emp_code`. |
| 2 | Attendance database | Duplicate attendance records for the same employee and date must be prevented. | Submit duplicate attendance records for one employee and date. | Added a unique compound index on `attendance_logs.emp_code` and `attendance_logs.date`. |
| 3 | Punch-in | Concurrent requests can attempt to create the same daily attendance record. | Send two punch-in requests for the same employee at nearly the same time. | The unique index provides database-level protection. Duplicate-key errors should be handled as conflicts. |
| 4 | Attendance listing | The query must use the actual attendance collection and apply the requested filters and sorting. | Call `GET /attendance` and verify returned records and ordering. | Used `attendance_logs` and checked the endpoint response. |
| 5 | Attendance regularization | Internal MongoDB fields may appear in the response when the API contract does not allow them. | Compare the PATCH response with the OpenAPI schema. | Review the response mapping and remove fields not required by the contract. |
| 6 | Department trend | Repeated database queries inside a date loop can be inefficient with a large dataset. | Inspect database query counts over a multi-day date range. | Identified aggregation-based gap filling as an improvement; verify before claiming it is implemented. |
| 7 | Explain endpoint | Returning execution statistics for only one supported target leaves other explain targets incomplete. | Test every documented target under `/admin/explain/{endpoint}`. | Verified `attendance_list`; the remaining targets require implementation and testing. |

## Not considered defects

A conflict response when an attendance record has already been punched out can be correct behavior. Gaps in MongoDB-generated IDs after deleting records are also normal and do not indicate a defect by themselves.

This review records the issues and checks identified during development. Each fix should be verified against the OpenAPI contract before being described as complete.