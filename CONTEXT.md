# Glossary

## Site

A physical location (building or facility) where lab work happens. Sites are
flat — they do not nest inside other Sites, and they do not move. Adding a
Site means an organization started operating out of a new building.

Sites are modeled as their own entity (`sites` table) scoped to an
organization.

## Room

Free-text descriptor of where inside a Site a piece of Equipment lives
(e.g. "Lab 204"). Rooms are **not** entities — they are a string column on
Equipment. Filtering/grouping by Room is done client-side over the equipment
list.

## Equipment.location

Free-text on-bench spot description (e.g. "Bench 4, north wall"). Distinct
from Room: Room says *which room*, `location` says *where in the room*.

## SITE_MANAGER

Additive org role for the person accountable for the facility's equipment
records — typically a lab manager. Distinguished from a regular MEMBER by
the ability to perform **regulated-data edits**, not by basic equipment
creation. Any member can register a piece of equipment; only a SITE_MANAGER
or ADMIN can edit its calibration history, status, serial, install date,
manufacturer/model, or archive it. Site CRUD (renaming, archiving a
building) is also restricted to SITE_MANAGER + ADMIN.

Rationale: calibration dates and equipment status are GLP-relevant
assertions that a piece of equipment is fit-for-use; this is a lab-manager
call, not a benchwork call.
