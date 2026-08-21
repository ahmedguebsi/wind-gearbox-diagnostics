# Wind Turbine Status and Reliability Analysis Report (2016)

**Prepared by:** Wind Turbine Reliability Engineer & FMEA Specialist  
**Subject:** Exhaustive Factual Reliability Analysis of the 2016 Kelmarsh Wind Farm Status Dataset  
**Date:** August 11, 2026

## 1. Executive Summary

This report provides a formal, comprehensive reliability assessment of the six wind turbines (Kelmarsh 1 through Kelmarsh 6) using the status log files from 2016. The dataset contains 14,019 status and alarm transitions across a cumulative period from January 14, 2016, to December 29, 2016. A total of 120 unique event codes were identified, capturing operating states, warnings, mechanical/electrical faults, and communication disruptions.

Key findings from an engineering and Failure Modes and Effects Analysis (FMEA) perspective include:
- **Fleet-Wide Curtailments:** Multiple concurrent fleet-wide shutdowns under Code 8000 (Park Master Stop) were identified on Feb 11, Sep 7, and Oct 31, 2016, representing grid-level or operator-requested curtailments rather than localized asset failures.
- **Brake Accumulator Jitter:** Kelmarsh 1 experienced a high frequency of Brake Accumulator Defects (Code 5720, 68 occurrences) and Timeout Brake Closed (Code 2125, 22 occurrences with 1,227 hours), indicating localized sensor or hydraulic wear on its mechanical braking system.
- **Major Gearbox Failures:** Kelmarsh 5 suffered multiple localized low gearbox oil pressure stops (Code 1510) starting January 26, 2016, resulting in a major 95-hour outage, pointing to a localized pump or seal failure.
- **Bearing Heat Anomaly:** Kelmarsh 2 experienced consecutive bearing over-temperature warnings (Codes 1700 and 1710) on January 29-30, 2016, triggering automatic power reductions (Code 75) to prevent physical degradation.
- **Common-Cause Auxiliary Failure:** Both Kelmarsh 2 and Kelmarsh 5 experienced simultaneous, long-duration breakdown of obstacle lights (Code 5000) starting on November 1, 2016, indicating potential lightning strike, power surge, or common substation relay damage.

## 2. Dataset Overview

The Kelmarsh wind farm dataset analyzed in this study consists of six SCADA-exported status log files covering the calendar year 2016. Each turbine is represented by a single file. The table below outlines the file details, record counts, active date ranges, and cumulative log durations (including all concurrent events).

| Turbine | File Name | Record Count | First Log Entry | Last Log Entry |
| --- | --- | --- | --- | --- |
| Kelmarsh 1 | Status_Kelmarsh_1_2016-01-03_-_2017-01-01_228.csv | 2,122 | 2016-01-14 19:28:03 | 2016-12-27 15:24:04 |
| Kelmarsh 2 | Status_Kelmarsh_2_2016-01-03_-_2017-01-01_229.csv | 1,790 | 2016-01-21 14:11:59 | 2016-12-27 15:27:25 |
| Kelmarsh 3 | Status_Kelmarsh_3_2016-01-03_-_2017-01-01_230.csv | 2,873 | 2016-01-27 15:56:48 | 2016-12-29 11:45:05 |
| Kelmarsh 4 | Status_Kelmarsh_4_2016-01-03_-_2017-01-01_231.csv | 1,929 | 2016-02-04 18:49:54 | 2016-12-27 15:27:27 |
| Kelmarsh 5 | Status_Kelmarsh_5_2016-01-03_-_2017-01-01_232.csv | 2,116 | 2016-01-24 15:12:45 | 2016-12-29 12:23:20 |
| Kelmarsh 6 | Status_Kelmarsh_6_2016-01-03_-_2017-01-01_233.csv | 3,189 | 2016-02-05 15:07:06 | 2016-12-29 13:32:34 |
| **Total** | **6 Files** | **14,019** | **2016-01-14 19:28:03** | **2016-12-29 13:32:34** |

## 3. SCADA Classification & Categorization

The SCADA status logs utilize a structured, multi-tier classification system consisting of three main categorical descriptors: Status Categories, IEC Categories, and Service Contract Categories.

### 3.1 Status Categories

Status categories denote the operational level of the alarm. The fleet-wide distribution is as follows:

| Status Category | Description / Interpretation | Record Count | Percentage |
| --- | --- | --- | --- |
| Informational | Non-fault operations, environment tracking, or automated stage transitions. | 12,549 | 89.51% |
| Stop | Turbine is actively shut down or prevented from operating due to fault or request. | 751 | 5.36% |
| Warning | Turbine remains operational but a subsystem parameter is out of normal range. | 553 | 3.94% |
| Communication | Loss of SCADA network connection prevents status telemetry. | 166 | 1.18% |

### 3.2 IEC Categories

The IEC standard classification system segments turbine performance and environmental constraints:

| IEC Category | Record Count | Percentage | Operational Significance |
| --- | --- | --- | --- |
| Full Performance | 6,705 | 47.83% | System is fully operational and generating power under normal conditions. |
| Out of Environmental Specification | 5,866 | 41.84% | Turbine is paused or curtailed because ambient wind or temperature is outside design limits. |
| UNKNOWN – REQUIRES CONFIRMATION | 533 | 3.80% | No standard IEC category assigned in SCADA export. |
| Technical Standby | 409 | 2.92% | Turbine is healthy but waiting for wind or grid synchronization. |
| Forced outage | 306 | 2.18% | Unplanned shutdown due to active subsystem mechanical or electrical failure. |
| Scheduled Maintenance | 131 | 0.93% | Shutdown or brake application for planned technician intervention or on-site manual work. |
| Out of Electrical Specification | 43 | 0.31% | Grid voltage or frequency is outside acceptable grid-code tolerances. |
| Requested Shutdown | 17 | 0.12% | Remote or manual park request (e.g. curtailment or fleet-wide stop). |
| Partial Performance | 9 | 0.06% | Operational under a warning state with automatic power curtailment to protect components. |

### 3.3 Service Contract Categories

The service contract categorizations define contract-relevant operational groupings:

| Service Contract Category | Record Count | Percentage |
| --- | --- | --- | 
| System OK (32) | 6,359 | 45.36% |
| External stop (low wind speed)  (5) | 5,391 | 38.45% |
| Operating states  (28) | 961 | 6.85% |
| Warnings (27) | 625 | 4.46% |
| Manual stop (service)  (9) | 265 | 1.89% |
| UNKNOWN – REQUIRES CONFIRMATION | 166 | 1.18% |
| External stop (grid) (4) | 52 | 0.37% |
| Generator and Converter errors (20) | 41 | 0.29% |
| Remote stop (30) | 40 | 0.29% |
| Sensor error (21) | 33 | 0.24% |
| Repeated error  (25) | 19 | 0.14% |
| Safety stop of WEC (15) | 14 | 0.10% |
| Safety chain (13) | 14 | 0.10% |
| Mechanical error (23) | 12 | 0.09% |
| Overspeed (14) | 8 | 0.06% |
| Emergency stop switch (Nacelle) (11) | 5 | 0.04% |
| Emergency stop switch (Converter) (12) | 5 | 0.04% |
| Electrical error (24) | 4 | 0.03% |
| Pitch errors (18) | 2 | 0.01% |
| Controller error of the WP3100 (16) | 2 | 0.01% |
| WEC Shutdown (1) | 1 | 0.01% |

## 4. Top Event Frequencies

A critical FMEA step is identifying high-frequency events. The top 5 events for each Status Category across the fleet are detailed below.

### 4.1 Most Frequent Informational Events

| Event Code | Message | IEC Category | Occurrence Count | Total Duration (Hours) | Average Duration (Hours) |
| --- | --- | --- | --- | --- | --- |
| 0 | System OK | Full Performance | 6352 | 10982.69 | 1.73 |
| 10 | Wind < start wind | Out of Environmental Specification | 5386 | 71.23 | 0.01 |
| 65 | Absence of wind during run-up | Out of Environmental Specification | 475 | 18.17 | 0.04 |
| 6410 | Manual yaw | Full Performance | 134 | 799.59 | 5.97 |
| 1552 | Gearbox warm-up stage | Full Performance | 64 | 8.17 | 0.13 |

### 4.1 Most Frequent Stop Events

| Event Code | Message | IEC Category | Occurrence Count | Total Duration (Hours) | Average Duration (Hours) |
| --- | --- | --- | --- | --- | --- |
| 710 | Battery test | Technical Standby | 258 | 14.23 | 0.06 |
| 20 | Manual stop - on site | Scheduled Maintenance | 117 | 369.77 | 3.16 |
| 6200 | Cable autounwind | Technical Standby | 68 | 17.28 | 0.25 |
| 3500 | Grid loss | Out of Electrical Specification | 33 | 236.93 | 7.18 |
| 5760 | Hydraulic oil flushing operation | Technical Standby | 28 | 4.67 | 0.17 |

### 4.1 Most Frequent Warning Events

| Event Code | Message | IEC Category | Occurrence Count | Total Duration (Hours) | Average Duration (Hours) |
| --- | --- | --- | --- | --- | --- |
| 8400 | Comm. failure FPM | Full Performance | 66 | 341.94 | 5.18 |
| 2550 | Overload generator fan 1 | Forced outage | 42 | 275.86 | 6.57 |
| 2650 | Overload generator fan 2 | Forced outage | 38 | 273.39 | 7.19 |
| 2655 | Overload generator fan 3 | Forced outage | 38 | 273.38 | 7.19 |
| 785 | Error brake resistor CHP | Full Performance | 11 | 220.01 | 20.00 |

### 4.1 Most Frequent Communication Events

| Event Code | Message | IEC Category | Occurrence Count | Total Duration (Hours) | Average Duration (Hours) |
| --- | --- | --- | --- | --- | --- |

## 5. Subsystem-Specific Technical Analysis

This section classifies event codes based on major engineering subsystems, as required for FMEA failure mode mapping.

### 5.1 Gearbox-related Events
Includes gearbox heating, warm-up stages, overload pumps, implausible speed readings, and bearing over-temperatures.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 1552 | Gearbox warm-up stage | Informational | 64 | 8.17 |
| 1555 | Gear heating enabled | Informational | 49 | 24.87 |
| 1825 | Overload gear bypass filter | Warning | 6 | 241.46 |
| 1510 | Low gearbox oil pressure | Stop | 4 | 98.37 |
| 1560 | Manual operation fan gear | Informational | 4 | 0.04 |
| 1565 | Manual operation gear heating | Informational | 3 | 0.01 |
| 75 | Reduced power gearbox | Warning | 2 | 16.37 |
| 1620 | Implausible gear speed | Stop | 2 | 0.71 |
| 1700 | High temp. gear bearing 1 | Warning | 2 | 18.31 |
| 1710 | High temp. gear bearing 2 | Warning | 2 | 18.31 |
| 1800 | Overload gear oil pump | Stop | 2 | 9.46 |
| 1922 | Particle Gear Alarm 10min | Warning | 1 | 0.06 |
| **Total** | | | **141** | **436.14** |

### 5.1 Bearing-related Events
Standard warning codes for high temperatures on gear bearing 1 and gear bearing 2.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 1700 | High temp. gear bearing 1 | Warning | 2 | 18.31 |
| 1710 | High temp. gear bearing 2 | Warning | 2 | 18.31 |
| **Total** | | | **4** | **36.62** |

### 5.1 Oil-related Events
Events relating to low oil pressure, pump overload, or hydraulic oil flushing.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 5760 | Hydraulic oil flushing operation | Stop | 28 | 4.67 |
| 1510 | Low gearbox oil pressure | Stop | 4 | 98.37 |
| 1800 | Overload gear oil pump | Stop | 2 | 9.46 |
| **Total** | | | **34** | **112.51** |

### 5.1 Lubrication-related Events
Lubrication pump errors specifically in the pitch control system.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 850 | Error lubrication pump pitch | Warning | 3 | 20.42 |
| **Total** | | | **3** | **20.42** |

### 5.1 Heating-related Events
Covers gear heating, generator heating, and control box heating/fan defects.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 1555 | Gear heating enabled | Informational | 49 | 24.87 |
| 1565 | Manual operation gear heating | Informational | 3 | 0.01 |
| 2674 | Overload generator heating | Warning | 2 | 3.37 |
| 2900 | Manual operation generator heating | Informational | 2 | 0.01 |
| 7057 | Heating/fan top box faulty | Warning | 2 | 265.97 |
| **Total** | | | **58** | **294.22** |

### 5.1 Cooling-related Events
Overloads or manual interventions on generator, transformer, gearbox, or top box cooling fans.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 2550 | Overload generator fan 1 | Warning | 42 | 275.86 |
| 2650 | Overload generator fan 2 | Warning | 38 | 273.39 |
| 2655 | Overload generator fan 3 | Warning | 38 | 273.38 |
| 3875 | Overload transf. fan inlet air | Warning | 6 | 241.46 |
| 2910 | Manual operation generator fan 1 | Informational | 5 | 12.23 |
| 1560 | Manual operation fan gear | Informational | 4 | 0.04 |
| 2920 | Manual operation generator fan 2 | Informational | 4 | 0.05 |
| 2930 | Manual operation generator fan 3 | Informational | 4 | 0.05 |
| 3870 | Overload transformer fan outlet air | Warning | 4 | 317.49 |
| 7057 | Heating/fan top box faulty | Warning | 2 | 265.97 |
| **Total** | | | **147** | **1659.92** |

### 5.1 Temperature-related Events
Specific warnings indicating bearing temperatures have exceeded normal bounds.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 1700 | High temp. gear bearing 1 | Warning | 2 | 18.31 |
| 1710 | High temp. gear bearing 2 | Warning | 2 | 18.31 |
| **Total** | | | **4** | **36.62** |

### 5.1 Vibration/Oscillation-related Events
Tower oscillation warnings (X and Y directions, Levels 1 and 2), tower oscillation encoder faults, and maximum rotor acceleration.

| Event Code | Message | Status Category | Occurrence Count | Total Cumulative Duration (Hours) |
| --- | --- | --- | --- | --- |
| 4588 | Oscillation encoder tower | Stop | 17 | 40.99 |
| 4540 | Tower oscillation X level 2 | Stop | 6 | 1.57 |
| 4510 | Tower oscillation Y level 1 | Stop | 4 | 0.57 |
| 4520 | Tower oscillation X level 1 | Stop | 3 | 0.54 |
| 59 | Max. acceleration | Warning | 2 | 0.03 |
| **Total** | | | **32** | **43.70** |

## 6. Maintenance, Repair, and Failure Analysis

### 6.1 Scheduled Maintenance vs. Forced Outages
SCADA logs categorize active outages under distinct IEC Performance standards:
- **Scheduled Maintenance:** Strictly defined by Event Codes **20** (Manual stop - on site, 117 occurrences), **25** (Manual stop without login, 10 occurrences), and **210** (Manual brake, 4 occurrences). Combined, these represent **131 scheduled service records** with a cumulative duration of **399.53 hours**.
- **Forced Outages:** An unplanned shutdown triggered by any of **39 unique event codes** (e.g. Code 3110: Frequency converter error, Code 1510: Low gearbox oil pressure, Code 100: Safety chain open). Forced outages represent **306 separate fault events** across the fleet.

### 6.2 Service Event Analysis
Service and technician interventions are categorized under the Service Contract Category . This category contains 265 records across four codes:
- **Code 20 (Manual stop - on site):** 117 occurrences, total duration of 369.77 hours. This is the main indicator of on-site technician service.
- **Code 6410 (Manual yaw):** 134 occurrences, total duration of 799.59 hours. Indicates yaw calibration or orientation testing during maintenance.
- **Code 25 (Manual stop without login):** 10 occurrences, total duration of 23.96 hours. Represents quick local stops without SCADA session initialization.
- **Code 210 (Manual brake):** 4 occurrences, total duration of 5.80 hours. Local application of mechanical rotor brake.

### 6.3 Missing Commentary Data
**CRITICAL NOTE FOR FMEA:** The SCADA-exported  column has **0 non-null records (100% missing)** across all 14,019 rows. There is no qualitative commentary or text descriptions regarding repairs, specific parts swapped (e.g. sensors, pumps), or root-cause resolutions. Reliability analysis is restricted to categorical event codes and duration metrics.

## 7. Recurring Events & Major Downtime Causes

The following standard failure modes represent the largest cumulative contributors to fleet downtime (excluding normal operational modes):

1. **Timeout Brake Closed (Code 2125 - Warning):** 74 occurrences, accumulating **1,611.30 hours** of warning state. This indicates an ongoing mechanical or sensor issue with the brake caliper release timing, concentrated heavily on Kelmarsh 1 (1,227 hours).
2. **Breakdown Obstacle Light (Code 5000 - Warning):** 16 occurrences, accumulating **2,182.34 hours** of warning state across the fleet, driven by extremely long-duration active warning phases on Kelmarsh 2 (1,291 hours) and Kelmarsh 5 (235 hours).
3. **Cable Panel Breaker Open (Code 3835 - Informational):** 4 occurrences, accumulating **850.52 hours** of warning state.
4. **Frequency Converter Error (Code 3110 - Stop):** 14 occurrences, accumulating **516.49 hours** of forced outage downtime, representing the largest physical component downtime cause.
5. **Park Master Stop (Code 8000 - Stop):** 17 occurrences, accumulating **389.64 hours** of requested shutdown. This represents fleet-wide external curtailments.
6. **Manual Stop - On Site (Code 20 - Stop):** 117 occurrences, accumulating **369.77 hours** of scheduled maintenance downtime.
7. **Comm. Failure FPM (Code 8400 - Warning):** 66 occurrences, accumulating **341.94 hours** of warning state.
8. **Overload Generator Cooling Fans (Codes 2550, 2650, 2655 - Warning):** 118 occurrences, accumulating **822.63 hours** of warning state across generator fans 1, 2, and 3.
9. **Grid Loss (Code 3500 - Stop):** 33 occurrences, accumulating **236.93 hours** of external electrical standby downtime.
10. **Error Brake Resistor CHP (Code 785 - Warning):** 11 occurrences, accumulating **220.01 hours**.

## 8. Candidate Events for Anomaly-Validation Studies

These five historical cases present high-fidelity, distinct operational anomalies ideal for validating predictive maintenance models:

### Case 1: Kelmarsh 5 - Active Gearbox Oil Pressure Failure
- **Date Range:** January 26, 2016, to February 2, 2016
- **Significance:** A progressive mechanical failure sequence on Kelmarsh 5. It began with brief low gearbox oil pressure stops (Code 1510) and culminated in a major unplanned downtime event lasting **95 hours, 3 minutes, 24 seconds** from Jan 28 to Feb 1. It is followed by an immediate gearbox warm-up sequence upon restart.
- **Sequence Table:**

| Timestamp Start | Timestamp End | Event Code | Message | Status | Duration |
| --- | --- | --- | --- | --- | --- |
| 2016-01-26 16:54:08 | 2016-01-26 16:56:14 | 1510 | Low gearbox oil pressure | Stop | 00:02:06 |
| 2016-01-27 09:34:42 | 2016-01-27 09:36:13 | 1510 | Low gearbox oil pressure | Stop | 00:01:31 |
| 2016-01-27 09:41:14 | 2016-01-27 09:44:51 | 1552 | Gearbox warm-up stage | Informational | 00:03:37 |
| 2016-01-27 09:47:42 | 2016-01-27 09:48:07 | 1552 | Gearbox warm-up stage | Informational | 00:00:25 |
| 2016-01-27 09:51:14 | 2016-01-27 09:51:25 | 1552 | Gearbox warm-up stage | Informational | 00:00:11 |
| 2016-01-27 10:20:57 | 2016-01-27 10:23:53 | 1552 | Gearbox warm-up stage | Informational | 00:02:56 |
| 2016-01-28 16:01:18 | 2016-02-01 15:04:42 | 1510 | Low gearbox oil pressure | Stop | 95:03:24 |
| 2016-02-01 15:06:49 | 2016-02-01 15:18:24 | 1552 | Gearbox warm-up stage | Informational | 00:11:35 |
| 2016-02-02 18:51:32 | 2016-02-02 22:06:47 | 1510 | Low gearbox oil pressure | Stop | 03:15:15 |

### Case 2: Kelmarsh 2 - Bearing Heat Anomaly and Automatic Power Reduction
- **Date Range:** January 29, 2016, to January 30, 2016
- **Significance:** On January 29, Kelmarsh 2 experienced twin warnings for high temperatures on gear bearings 1 & 2 (Codes 1700 & 1710) lasting ~16.5 hours. Concurrently, SCADA triggered a  alarm (Code 75, 15.4 hours), showing a closed-loop automated curtailment to prevent bearing seize. A second brief sequence of the same anomaly occurred on January 30.
- **Sequence Table:**

| Timestamp Start | Timestamp End | Event Code | Message | Status | Duration |
| --- | --- | --- | --- | --- | --- |
| 2016-01-29 11:54:26 | 2016-01-30 04:22:30 | 1710 | High temp. gear bearing 2 | Warning | 16:28:04 |
| 2016-01-29 11:57:05 | 2016-01-30 04:22:50 | 1700 | High temp. gear bearing 1 | Warning | 16:25:45 |
| 2016-01-29 12:48:22 | 2016-01-30 04:12:48 | 75 | Reduced power gearbox | Warning | 15:24:26 |
| 2016-01-30 05:44:45 | 2016-01-30 07:35:28 | 1710 | High temp. gear bearing 2 | Warning | 01:50:43 |
| 2016-01-30 05:46:42 | 2016-01-30 07:39:38 | 1700 | High temp. gear bearing 1 | Warning | 01:52:56 |
| 2016-01-30 06:38:23 | 2016-01-30 07:36:00 | 75 | Reduced power gearbox | Warning | 00:57:37 |

### Case 3: Fleet-Wide Concurrent Park Master Stop Events
- **Date Range:** Feb 11, Sep 7, and Oct 31, 2016
- **Significance:** Fleet-wide operational curtailments under Code 8000 (Park Master Stop). In all three cases, multiple turbines entered the stop state at the exact same second. The October 31 outage shut down the entire fleet (6 turbines) for exactly **52 hours, 46 minutes**, indicating a scheduled grid-level substation outage or operator curtailment.
- **Sequence Table:**

| Turbine | Timestamp Start | Timestamp End | Event Code | Message | Status | Duration |
| --- | --- | --- | --- | --- | --- | --- |
| Kelmarsh 1 | 2016-02-11 10:19:24 | 2016-02-11 13:57:32 | 8000 | Park master stop | Stop | 03:38:08 |
| Kelmarsh 6 | 2016-02-11 10:19:24 | 2016-02-11 11:27:00 | 8000 | Park master stop | Stop | 01:07:36 |
| Kelmarsh 2 | 2016-02-11 10:19:24 | 2016-02-11 14:11:34 | 8000 | Park master stop | Stop | 03:52:10 |
| Kelmarsh 3 | 2016-02-11 10:19:24 | 2016-02-11 13:58:15 | 8000 | Park master stop | Stop | 03:38:51 |
| Kelmarsh 4 | 2016-02-11 10:19:24 | 2016-02-11 13:59:50 | 8000 | Park master stop | Stop | 03:40:26 |
| Kelmarsh 5 | 2016-09-07 06:21:09 | 2016-09-07 15:51:47 | 8000 | Park master stop | Stop | 09:30:38 |
| Kelmarsh 3 | 2016-09-07 06:21:09 | 2016-09-07 15:51:46 | 8000 | Park master stop | Stop | 09:30:37 |
| Kelmarsh 1 | 2016-09-07 06:21:11 | 2016-09-07 15:50:45 | 8000 | Park master stop | Stop | 09:29:34 |
| Kelmarsh 2 | 2016-09-07 06:21:11 | 2016-09-07 15:51:50 | 8000 | Park master stop | Stop | 09:30:39 |
| Kelmarsh 4 | 2016-09-07 06:21:11 | 2016-09-07 15:51:49 | 8000 | Park master stop | Stop | 09:30:38 |
| Kelmarsh 6 | 2016-09-07 06:21:12 | 2016-09-07 15:51:50 | 8000 | Park master stop | Stop | 09:30:38 |
| Kelmarsh 3 | 2016-10-31 07:55:33 | 2016-11-02 12:41:36 | 8000 | Park master stop | Stop | 52:46:03 |
| Kelmarsh 4 | 2016-10-31 07:55:33 | 2016-11-02 12:41:35 | 8000 | Park master stop | Stop | 52:46:02 |
| Kelmarsh 2 | 2016-10-31 07:55:34 | 2016-11-02 12:41:36 | 8000 | Park master stop | Stop | 52:46:02 |
| Kelmarsh 5 | 2016-10-31 07:55:34 | 2016-11-02 12:41:36 | 8000 | Park master stop | Stop | 52:46:02 |
| Kelmarsh 1 | 2016-10-31 07:55:34 | 2016-11-02 12:43:49 | 8000 | Park master stop | Stop | 52:48:15 |
| Kelmarsh 6 | 2016-10-31 07:55:34 | 2016-11-02 12:41:36 | 8000 | Park master stop | Stop | 52:46:02 |

### Case 4: Kelmarsh 2 & 5 - Concurrent Auxiliary System Failures
- **Date Range:** November 1, 2016, onwards
- **Significance:** A simultaneous breakdown of obstacle lights (Code 5000) occurred on Kelmarsh 2 (16:08:41) and Kelmarsh 5 (16:18:40) within 10 minutes of each other on Nov 1, 2016. The outages lasted for 770 hours on Kelmarsh 2 and 235 hours on Kelmarsh 5. This suggests a common-cause event (e.g. lightning strike or voltage surge on a shared auxiliary power circuit) that damaged components on both assets.
- **Sequence Table:**

| Turbine | Timestamp Start | Timestamp End | Event Code | Message | Status | Duration |
| --- | --- | --- | --- | --- | --- | --- |
| Kelmarsh 2 | 2016-11-01 16:08:41 | 2016-12-03 18:41:28 | 5000 | Breakdown obstacle light | Warning | 770:32:47 |
| Kelmarsh 5 | 2016-11-01 16:18:40 | 2016-11-11 12:03:07 | 5000 | Breakdown obstacle light | Warning | 235:44:27 |

### Case 5: Kelmarsh 1 & 2 - Emergency Stop Nacelle and Filter Overload Correlations
- **Date Range:** January 14, 2016 (Kelmarsh 1) and January 21, 2016 (Kelmarsh 2)
- **Significance:** On Kelmarsh 1, an Emergency Stop Nacelle (Code 111) was triggered on Jan 14 at 19:28:03, lasting **211 hours**. Just 2 seconds later (19:28:05), an Overload Gear Bypass Filter (Code 1825) was triggered, lasting **209 hours**. On Jan 21, Kelmarsh 2 went into an Emergency Stop Nacelle (Code 111) at 14:11:59 (duration UNKNOWN), and 1 second later (14:12:00) experienced an Overload Gear Bypass Filter (Code 1825) lasting 2 hours. This suggests that manual emergency stops are tightly linked to hydraulic pressure transients that overload bypass filters upon manual trip or hydraulic dump.
- **Sequence Table:**

| Turbine | Timestamp Start | Timestamp End | Event Code | Message | Status | Duration |
| --- | --- | --- | --- | --- | --- | --- |
| Kelmarsh 1 | 2016-01-14 19:28:03 | 2016-01-23 14:36:32 | 111 | Emergency stop nacelle | Stop | 211:08:29 |
| Kelmarsh 1 | 2016-01-14 19:28:05 | 2016-01-23 12:38:11 | 1825 | Overload gear bypass filter | Warning | 209:10:06 |
| Kelmarsh 2 | 2016-01-21 14:11:59 | - | 111 | Emergency stop nacelle | Stop | - |
| Kelmarsh 2 | 2016-01-21 14:12:00 | 2016-01-21 16:26:13 | 1825 | Overload gear bypass filter | Warning | 02:14:13 |
