---
title: Experiments and runs
summary: How runs work — planning, executing, completing, and recording deviations.
keywords: [experiment, run, execution, deviation, complete, step]
---

# Experiments and runs

Batchrite uses three related terms that are easy to confuse. A **protocol** is the reusable template — it defines the steps, parameters, and roles but is never modified during lab work. When you create a run, Batchrite takes a snapshot of the chosen protocol and stores it inside the run's graph. That snapshot is what you actually execute; the original protocol stays clean. An **experiment** is an optional grouping layer that collects related runs together under a shared name (for example, all the runs that test the same cell-culture condition). A **run** is the execution itself — the thing that has a status, records data step by step, and ultimately produces a completed batch record.

In short: **Protocol → snapshot → Run**; **Experiment** groups one or more runs.

## What you can do

- Plan a run by choosing a protocol and optionally adjusting step parameters for just this execution before starting.
- Assign team members to roles (swimlanes) defined in the protocol.
- Start the run and execute each step in sequence, entering values and marking steps complete.
- Attach files and photos to individual steps or to the run as a whole.
- Add notes to the run at any time using the **Notes** tab.
- Record deviations by choosing **Completed with deviations** as the run outcome when finishing.
- Complete the run and select an outcome: **Completed normally**, **Completed with deviations**, or **Aborted**.
- Edit a completed run and provide a reason for each changed value (preserved in the audit trail).
- Download the run's SOP or Batch Record from the **Documents** section.

## How to plan a run

Runs are created from inside a project.

1. Open a project and click the **Runs** tab (or the **Experiments** tab to attach the run to an experiment).
2. Click **+ New Run**. A full-screen wizard opens titled **New Run**.
3. In the **Name** step, type a name for this run. Optionally select an experiment to assign the run to, and toggle **This run produces a lot** if the run will yield a manufacturing lot.
4. Click **Continue** to go to the **Protocol** step. Choose the protocol to base this run on, and select a version if you need a version other than the latest.
5. Click **Continue** to go to the **Parameters** step. You can override step parameters or equipment for just this run without editing the original protocol. Click **Skip · use defaults** to leave all protocol defaults unchanged.
6. Click **Continue** to go to the **Assignee** step. Assign project members to each role (swimlane). Click **Skip · assign later** if you prefer to do this after creation.
7. Click **Continue to review** and confirm the summary, then click **Create run**. Batchrite creates the run in **Planned** status and opens it.

## How to execute and complete a run

1. On the run page, confirm role assignments in the **Role Assignments** panel (you can reassign people here if needed), then click **Start Run**. The run moves to **Running** status.
2. Each team member assigned to a role sees their steps in a step-by-step wizard. Work through each step, entering values and clicking to mark it complete.
3. Use the **Notes** tab to add timestamped notes, and the **Attachments** tab to upload files or photos tied to the run or a specific step.
4. When all steps are complete, a prompt appears to confirm finishing. Choose a **Run outcome**:
   - **Completed normally** — all steps executed within specification.
   - **Completed with deviations** — the run finished but one or more deviations were recorded.
   - **Aborted** — the run stopped before normal completion.
5. Optionally add text in the **Outcome notes** field to summarise the result or reason for abort, then click **Complete Run**. The run moves to **Completed** status.
6. If you need to correct data after completion, click **Edit Run** on the completed run page. Batchrite asks for a reason for each changed value and preserves the original values in the audit trail. The run moves to **Edited** status after saving.
