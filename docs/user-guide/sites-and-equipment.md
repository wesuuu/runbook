---
title: Sites and equipment
summary: Registering sites and managing equipment, calibration, and expiry.
keywords: [site, room, equipment, calibration, expiry, location]
---

# Sites and equipment

Sites describe where your work physically happens — a building, campus, or
lab location. Each site contains equipment records that track what instruments
and tools are available, where they live in the building, and when they were
last calibrated. Scientists can select registered equipment while executing a
run, creating a clear audit trail linking data to the exact instrument used.

## What you can do

- Register sites and give each one a name and optional description.
- Add equipment records to a site, including the room, bench or spot, type,
  manufacturer, model, and serial number.
- Track calibration dates — last calibration and next calibration — and see at
  a glance which items are current, coming due, or expired.
- Set equipment status to Active, Maintenance, or Retired.
- Tag equipment for easy filtering.
- Filter the equipment table by name, serial number, type, status, or tag.
- Archive a site and automatically move all its equipment to another site.
- Designate one site as the default for new equipment.
- Grant site-manager access to specific team members (Admin only).

## How to register a site

1. Go to **Settings** and click the **Sites & Equipment** tab.
2. In the left rail under **Sites**, click **+ New**.
3. In the **New site** dialog, enter a **Name** (for example, "South Bay HQ") and an optional **Description**.
4. Click **Save**. The new site appears in the left rail and is selected automatically.

To rename an existing site, select it in the rail and click **Rename** in the
site header. To make a site the default, click **Set as default**. The default
site is pre-selected when adding new equipment.

## How to add equipment

1. Select the target site in the left rail under **Sites**.
2. Click **+ Add equipment** in the site header.
3. In the **New equipment** dialog, fill in the required fields:
   - **Name** — a descriptive label for the item.
   - **Site** — the site this equipment belongs to.
4. Optionally fill in **Type**, **Room**, **Bench / Spot**, **Description**, and **Tags**.
5. If you hold the Site Manager or Admin role, you can also set the regulated
   fields: **Manufacturer**, **Model**, **Serial**, **Status**,
   **Install date**, **Last calibration**, and **Next calibration**.
6. Click **Save changes**.

The equipment appears in the table. The **Calibration** column shows a green
checkmark when calibration is current, an amber countdown when it is due
within 30 days, and a red "Expired" badge when overdue.

To edit an existing item, click its row in the table. To archive an item,
hover over its row and click **Archive** (Site Manager or Admin only).

## How to archive a site

Archiving removes a site from pickers going forward. All equipment on the site
must be moved to another site first — the archive wizard guides you through
this.

1. Select the site you want to close and click **Archive** in the site header.
2. In step 1, choose a **Default destination site** for all equipment.
3. In step 2, review each piece of equipment and override individual
   destinations if needed.
4. In step 3, enter a **Reason** for archiving, check the acknowledgement, and
   click **Archive site & move** to confirm.

Past runs that reference the archived site retain their reference; only new
work is affected.
