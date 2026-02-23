# HSB Activation and Violation Check

## Scope

This document defines the structural rules and procedures for identifying, validating, and flagging HSB (Sobreaviso/Standby) activation sequences in crew scheduling calendars. 

## Main Rules

### Rule 1: HSB Duration Limits
- **Minimum:** 3 hours (180 minutes)
- **Maximum:** 12 hours (720 minutes)
- **Status:** Regulatory requirement. HSB periods outside this range are invalid and must be flagged.

### Rule 2: Maximum HSB Per Month
- **Limit:** 8 standby periods per calendar month
- **Status:** Regulatory requirement. Exceeding this triggers a violation.
- **Check:** Count all HSB events in the same calendar month; if count > 8, flag all excess HSB events, listing every one of them with dates into notes after the 1st HSB event.

### Rule 3: Rest After Unused HSB
- **Requirement:** After an HSB period that expires without activation (no ASB or FLIGHT following), a minimum of 12 hours (720 minutes) of rest is required before the next scheduled duty/flight.
- **Check:** If HSB expires unused, verify the gap to the next FLIGHT or ASB event is ≥ 720 minutes.

### Rule 4: Notification and Presentation Window
- **Standard bases (non-multi-airport regions):** 90 minutes to present at airport/designated location
  - Applies to: All bases except GRU, CGH, SDU, GIG
- **Multi-airport regions (São Paulo, Rio de Janeiro):** 150 minutes to present
  - Applies to: GRU (Guarulhos), CGH (Congonhas), SDU (Santos Dumont), GIG (Galeão)
- **Status:** Regulatory requirement. Travel time does NOT count toward duty limits.
- **Implementation:** Create a "Deslocamento" (Travel/Presentation) event in the calendar with specific duration (see section: Create Events).

### Rule 5: Combined Duty Limit (Tripulação Simples)
- **Requirement:** When HSB is followed by ASB or FLIGHT activation, the sum of HSB duration and subsequent duty/flight time **cannot exceed 16 hours (960 minutes)**.
- **Calculation:**
  ```
  Combined Duty = HSB Duration (minutes) + Following Event Duration (minutes)
  
  If Combined Duty > 960 minutes → VIOLATION
  ```
- **Status:** Regulatory requirement. Critical for fatigue risk management.
- **Exclusion:** Notification window (Deslocamento time) does NOT count toward duty time.

### Rule 6: Deslocamento Time Does Not Count Toward Duty
- **Principle:** The travel/presentation time window (90 or 150 minutes) is operational logistics, not duty time.
- **Example:** 
  - HSB starts at 08:00, ends at 12:00 (240 min HSB)
  - Notification received at 12:00 for flight departure at 17:30 (base GRU)
  - Presentation window: 12:00 + 150 min = 13:30 (crew must present by 13:30)
  - Actual duty calculation: 240 min (HSB) + flight duration (from 17:30 onward)
  - The 150-minute gap between HSB end and flight start does NOT add to duty time

---

## How to Handle Source

### Input Data Structure
Source data comes from `processed_events` (normalized from iFlightNeo):

```json
{
  "event_id": "HSB_001",
  "crew_id": "BP12345",
  "event_type": "HSB",
  "start_time": "2024-02-15T08:00:00Z",
  "end_time": "2024-02-15T12:00:00Z",
  "duration_minutes": 240,
  "base": "GRU",
  "attributes": {}
}
```

### Processing Steps

1. **Identify HSB Events**
   - Filter all events where `event_type == "HSB"`
   - Extract `start_time`, `end_time`, `duration_minutes`, `base`

2. **Validate HSB Duration**
   - Check Rule 1: Is 180 ≤ `duration_minutes` ≤ 720?
   - If NO → Create "Violation!" event (see section: Create Events)

3. **Check Monthly HSB Count**
   - Filter HSB events in the same calendar month
   - Count total HSB events
   - If count > 8 → Flag all excess HSB events with violation

4. **Find Following Event**
   - Search for the first event after `hsb.end_time` with type ASB or FLIGHT
   - If found → Proceed to Rule 5 (Combined Duty Limit)
   - If not found → Check Rule 3 (Rest After Unused HSB)

5. **Determine Presentation Window**
   - If `base` in [GRU, CGH, SDU, GIG] → notification_window = 150 minutes
   - Else → notification_window = 90 minutes
   - Presentation deadline = `hsb.end_time` + notification_window

6. **Validate Combined Duty (Rule 5)**
   - Calculate: `combined_duty = hsb.duration_minutes + following_event.duration_minutes`
   - If `combined_duty > 960` → Create "Violation!" event with reason "Beyond 16 hour duty time after HSB"
   - Else → Create "Deslocamento" event (see section: Create Events)

7. **Check Presentation Feasibility**
   - If `following_event.start_time` < `presentation_deadline` → Create "Violation!" event with reason "Deslocamento Time insuficient for established rules"

---

## Create Events: Deslocamento and Violation

### Event Creation Logic

After validating an HSB sequence, the calendar must be augmented with synthetic events:

#### Deslocamento Event (Valid HSB Activation)
When HSB is followed by ASB or FLIGHT **and all rules pass**:

**Condition:**
- HSB duration is valid (Rule 1)
- Combined duty ≤ 16 hours (Rule 5)
- Presentation is feasible (Rule 4)

**Event Properties:**
```json
{
  "event_id": "DESLOCAMENTO_<HSB_ID>",
  "crew_id": "<same as HSB>",
  "event_type": "DESLOCAMENTO",
  "start_time": "<HSB.end_time>",
  "end_time": "<HSB.end_time + (notification_window - 2) minutes>",
  "duration_minutes": "<notification_window - 2>",
  "base": "<HSB.base>",
  "notes": "Presentation window to airport/designated location",
  "parent_hsb_id": "<HSB.event_id>",
  "attributes": {
    "notification_window_full": "<notification_window>",
    "presentation_deadline": "<HSB.end_time + notification_window>"
  }
}
```

**Duration Calculation (Visual Overlap Prevention):**
- Multi-airport bases (GRU, CGH, SDU, GIG): duration = 150 - 2 = **148 minutes**
- Other bases: duration = 90 - 2 = **88 minutes**

**Rationale:** By using (notification_window - 2) minutes, the Deslocamento event ends 2 minutes before the following ASB or FLIGHT event starts, preventing visual overlap in calendar views while maintaining clarity of the transition.

---

#### Violation! Event (Rule Violation Detected)
When HSB validation fails for any reason:

**Condition:**
- HSB duration invalid (Rule 1)
- Monthly HSB count exceeded (Rule 2)
- Rest after unused HSB insufficient (Rule 3)
- Combined duty exceeds 16 hours (Rule 5)
- Presentation window insufficient (Rule 4 feasibility check)

**Event Properties:**
```json
{
  "event_id": "VIOLATION_<HSB_ID>_<violation_type>",
  "crew_id": "<same as HSB>",
  "event_type": "VIOLATION",
  "start_time": "<HSB.end_time>",
  "end_time": "<HSB.end_time + 10 minutes>",
  "duration_minutes": 10,
  "base": "<HSB.base>",
  "notes": "<violation_description>",
  "parent_hsb_id": "<HSB.event_id>",
  "attributes": {
    "violation_type": "<type_code>",
    "severity": "high|medium|low"
  }
}
```

**Duration:** Always **10 minutes** for visibility and audit trail consistency.

**Placement:** Violation event starts immediately after HSB end_time, making it visually distinct but close enough to indicate association.

---

## Deslocamento

### Definition
Deslocamento (literally "displacement" or "transfer") represents the legal notification-to-presentation period during which a crew member must travel from their designated standby location to the airport or operational facility to assume an assigned duty/flight.

### Rules by Base

#### Multi-Airport Regions: 150 Minutes
**Applies to:**
- **GRU** (Guarulhos International, São Paulo)
- **CGH** (Congonhas, São Paulo)
- **SDU** (Santos Dumont, Rio de Janeiro)
- **GIG** (Galeão International, Rio de Janeiro)

**Rationale:** These regions have multiple airports; 150 minutes accounts for intra-city travel complexity and traffic variability.

**Calendar Event Duration:** 148 minutes (150 - 2, to prevent visual overlap)

**Example:**
- HSB expires: 12:00
- Notification window: 150 minutes
- Presentation deadline: 13:30
- Deslocamento event: 12:00 to 13:28 (148 min duration)
- Following FLIGHT: 13:30 start (2 min buffer)

#### Standard Bases: 90 Minutes
**Applies to:** All other home bases (e.g., BPS, GIG, MGF, etc.)

**Rationale:** Standard operational assumption for single-airport or smaller hub transitions.

**Calendar Event Duration:** 88 minutes (90 - 2, to prevent visual overlap)

**Example:**
- HSB expires: 08:00
- Notification window: 90 minutes
- Presentation deadline: 09:30
- Deslocamento event: 08:00 to 09:28 (88 min duration)
- Following ASB: 09:30 start (2 min buffer)

### Key Principle
**Deslocamento time is NOT counted in duty limit calculations.** It is a transition period, not operational duty. The 16-hour rule applies only to HSB + following activity duration, not to Deslocamento.

---

## Violation! (Violation Event Rules)

### Purpose
Violation! events are red-flag indicators created in the calendar to alert crew schedulers and crew members to rule breaches that require corrective action or manual review.

### Event Type Codes

| Violation Type | Code | Severity | Description |
|---|---|---|---|
| Invalid HSB Duration | `INVALID_HSB_DURATION` | High | HSB duration < 180 min or > 720 min |
| Monthly Limit Exceeded | `MONTHLY_HSB_EXCEEDED` | High | More than 8 HSB events in calendar month |
| Insufficient Rest (Unused HSB) | `INSUFFICIENT_REST_UNUSED_HSB` | High | Less than 12 hours rest after HSB without activation |
| Beyond 16-Hour Duty | `DUTY_LIMIT_EXCEEDED` | High | HSB + following event > 960 minutes |
| Insufficient Deslocamento | `INSUFFICIENT_DESLOCAMENTO` | High | Following event starts before presentation deadline |
| Check Leg Count | `CHECK_LEG_COUNT` | Medium | Following flight exceeds crew rotation limits (if applicable) |

### Notes Field Content

The **notes** field in a Violation! event must contain a **crew-facing explanation** of the violation. Format:

```
[VIOLATION TYPE]: <Brief Code>
Reason: <Human-readable explanation>
Details: <Quantitative data if applicable>
Action Required: <Corrective step(s)>
```

### Example Violation! Events

#### Example 1: Beyond 16-Hour Duty
```json
{
  "event_id": "VIOLATION_HSB_001_DUTY",
  "crew_id": "BP12345",
  "event_type": "VIOLATION",
  "start_time": "2024-02-15T12:00:00Z",
  "end_time": "2024-02-15T12:10:00Z",
  "duration_minutes": 10,
  "base": "GRU",
  "notes": "[DUTY_LIMIT_EXCEEDED]: Beyond 16 hour duty time after HSB\nReason: HSB (240 min) + FLIGHT_001 (600 min) = 840 min (14h). Total with connections would exceed 16h.\nDetails: HSB 08:00-12:00 + FLIGHT 13:30-23:30 = 16h cumulative.\nAction Required: Redistribute flight duties or reduce HSB duration.",
  "parent_hsb_id": "HSB_001",
  "attributes": {
    "violation_type": "DUTY_LIMIT_EXCEEDED",
    "severity": "high",
    "hsb_duration_minutes": 240,
    "following_event_duration_minutes": 600,
    "combined_duty_minutes": 840
  }
}
```

#### Example 2: Deslocamento Time Insufficient
```json
{
  "event_id": "VIOLATION_HSB_002_DESLOCAMENTO",
  "crew_id": "BP67890",
  "event_type": "VIOLATION",
  "start_time": "2024-02-16T09:00:00Z",
  "end_time": "2024-02-16T09:10:00Z",
  "duration_minutes": 10,
  "base": "BPS",
  "notes": "[INSUFFICIENT_DESLOCAMENTO]: Deslocamento Time insuficient for established rules\nReason: HSB ends 09:00 (Brasília, 90-min window = 10:30 deadline). FLIGHT_002 departs 10:15.\nDetails: Only 45 minutes between HSB end and flight start. Crew cannot present by 10:30.\nAction Required: Delay FLIGHT_002 or reschedule HSB.",
  "parent_hsb_id": "HSB_002",
  "attributes": {
    "violation_type": "INSUFFICIENT_DESLOCAMENTO",
    "severity": "high",
    "hsb_end_time": "2024-02-16T09:00:00Z",
    "notification_window_required_minutes": 90,
    "presentation_deadline": "2024-02-16T10:30:00Z",
    "following_event_start": "2024-02-16T10:15:00Z",
    "gap_minutes": 45
  }
}
```

#### Example 3: Invalid HSB Duration
```json
{
  "event_id": "VIOLATION_HSB_003_DURATION",
  "crew_id": "BP11111",
  "event_type": "VIOLATION",
  "start_time": "2024-02-17T14:00:00Z",
  "end_time": "2024-02-17T14:10:00Z",
  "duration_minutes": 10,
  "base": "GIG",
  "notes": "[INVALID_HSB_DURATION]: HSB period violates regulatory limits\nReason: HSB duration is 100 minutes. Minimum allowed is 180 minutes (3 hours).\nDetails: HSB 14:00-15:40 = 100 min. Not compliant with LATAM CCT 2019/2020.\nAction Required: Extend HSB to minimum 3 hours or remove entirely.",
  "parent_hsb_id": "HSB_003",
  "attributes": {
    "violation_type": "INVALID_HSB_DURATION",
    "severity": "high",
    "hsb_duration_minutes": 100,
    "minimum_required_minutes": 180,
    "maximum_allowed_minutes": 720
  }
}
```

#### Example 4: Monthly Limit Exceeded
```json
{
  "event_id": "VIOLATION_HSB_004_MONTHLY",
  "crew_id": "BP22222",
  "event_type": "VIOLATION",
  "start_time": "2024-02-25T10:00:00Z",
  "end_time": "2024-02-25T10:10:00Z",
  "duration_minutes": 10,
  "base": "CGH",
  "notes": "[MONTHLY_HSB_EXCEEDED]: Monthly HSB limit exceeded\nReason: This is the 9th HSB in February 2024. Maximum allowed is 8 per month.\nDetails: HSB events in Feb: HSB_001...HSB_009. Current event (HSB_009) exceeds quota.\nAction Required: Remove or reschedule one HSB event to next month (March).",
  "parent_hsb_id": "HSB_009",
  "attributes": {
    "violation_type": "MONTHLY_HSB_EXCEEDED",
    "severity": "high",
    "month": "2024-02",
    "hsb_count_current": 9,
    "hsb_limit_monthly": 8,
    "excess_count": 1
  }
}
```

---

## Implementation in VSCode

### Workflow
1. **Parse processed_events** for all HSB entries
2. **Apply Rules 1–4** sequentially (duration, monthly count, rest, notification window)
3. **Identify following events** (ASB or FLIGHT)
4. **Apply Rule 5** (combined duty limit)
5. **Generate output:**
   - If all rules pass → Create **Deslocamento** event
   - If any rule fails → Create **Violation!** event
6. **Augment processed_events** with new Deslocamento and Violation! entries
7. **Publish updated ICS calendar** with augmented events

### VSCode Snippets / Tasks
- Use the rule definitions above as checklist comments in automation scripts
- Tag violations with severity levels for dashboard filtering
- Archive violation events separately for compliance audit trails

---

## Summary Table

| Rule # | Rule Name | Limit | Violation Type | Action |
|---|---|---|---|---|
| 1 | HSB Duration | 3–12 hours | `INVALID_HSB_DURATION` | Create Violation! event |
| 2 | Monthly HSB Count | ≤ 8/month | `MONTHLY_HSB_EXCEEDED` | Create Violation! event |
| 3 | Rest After Unused HSB | ≥ 12 hours | `INSUFFICIENT_REST_UNUSED_HSB` | Create Violation! event |
| 4 | Notification Window | 90/150 min | `INSUFFICIENT_DESLOCAMENTO` | Create Violation! event |
| 5 | Combined Duty Limit | ≤ 16 hours | `DUTY_LIMIT_EXCEEDED` | Create Violation! event |
| — | Valid HSB + Activation | (Pass all rules) | — | Create Deslocamento event |

---

**Document Version:** 1.0  
**Last Updated:** 2024  
**Regulatory Reference:** LATAM Airlines CCT 2019/2020, Brazilian Labor Code (Código Consolidado das Leis do Trabalho)


## Operational Status (2026-02-23)

### Active Script
The active HSB checker in this repository is:
- `worker/dtl-hsb-rulecheck.py`

The legacy files below were removed from the repo and are no longer part of any workflow:
- `worker/hsb-ruleset.py`
- `worker/hsb-ruleset-dummy.py`

### Default Pipeline
Current worker loop order (`worker/worker_loop.py`):
1. `ingest_ics.py`
2. `init_parsing.py`
3. `checkout_creator.py`
4. `dayoff_parsing.py`
5. `dtl-singlecrew.py`
6. `dtl-hsb-rulecheck.py`
7. `publish_ics.py`

### Notes From Recent Validation
1. Duplicate chains seen in `roque.ics` were source-driven (parallel source rows), not from HSB checker reruns.
2. `dtl-hsb-rulecheck.py` runs in-loop and rewrites its own synthetic outputs each cycle.
3. Timezone handling remained correct in the validated runs.

### Useful Commands
Run the HSB checker manually for the default user:
```bash
docker compose exec -T worker sh -lc 'python /app/dtl-hsb-rulecheck.py'
```

Run HSB checker for a specific source UID:
```bash
docker compose exec -T worker sh -lc 'python /app/dtl-hsb-rulecheck.py --source-uid <SOURCE_UID>'
```

Run full default transform/publish sequence manually:
```bash
docker compose exec -T worker sh -lc 'python /app/init_parsing.py && python /app/checkout_creator.py && python /app/dayoff_parsing.py && python /app/dtl-singlecrew.py && python /app/dtl-hsb-rulecheck.py && python /app/publish_ics.py'
```
