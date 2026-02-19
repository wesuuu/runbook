#!/bin/bash
# Display all seed users and their credentials for quick reference during testing
# Usage: ./backend/scripts/show-seed-users.sh

cat << 'EOF'
╔════════════════════════════════════════════════════════════════════════════╗
║                      SEED USERS - TEST CREDENTIALS                        ║
║                     Default Password: password123                          ║
╚════════════════════════════════════════════════════════════════════════════╝

┌─ ADMIN ───────────────────────────────────────────────────────────────────┐
│ Email:       admin@bioprocess.com
│ Password:    password123
│ Role:        Organization Admin
│ Access:      Full system access
└───────────────────────────────────────────────────────────────────────────┘

┌─ UPSTREAM TEAM ───────────────────────────────────────────────────────────┐
│
│ Team Lead (Owner):
│   Email:     upstream.lead@bioprocess.com
│   Password:  password123
│   Role:      Team Owner
│   Projects:  ADMIN on "mAb Production v2"
│
│ Scientist (Member):
│   Email:     scientist1@bioprocess.com
│   Password:  password123
│   Role:      Team Member
│   Projects:  Member on "mAb Production v2"
│
└───────────────────────────────────────────────────────────────────────────┘

┌─ DOWNSTREAM TEAM ─────────────────────────────────────────────────────────┐
│
│ Team Lead (Owner):
│   Email:     downstream.lead@bioprocess.com
│   Password:  password123
│   Role:      Team Owner
│   Projects:  ADMIN on "Vaccine Formulation Study"
│              VIEW on "mAb Production v2"
│
│ Scientist (Member):
│   Email:     scientist2@bioprocess.com
│   Password:  password123
│   Role:      Team Member
│   Projects:  EDIT on "Vaccine Formulation Study"
│              MEMBER on "mAb Production v2"
│
└───────────────────────────────────────────────────────────────────────────┘

┌─ QA TEAM ─────────────────────────────────────────────────────────────────┐
│
│ Viewer (Member):
│   Email:     viewer@bioprocess.com
│   Password:  password123
│   Role:      Team Member (Read-only)
│   Projects:  VIEW on both projects
│
└───────────────────────────────────────────────────────────────────────────┘

╔════════════════════════════════════════════════════════════════════════════╗
║                             QUICK TEST MATRIX                             ║
╚════════════════════════════════════════════════════════════════════════════╝

Full Edit Access:
  • upstream.lead@bioprocess.com     (mAb Production)
  • downstream.lead@bioprocess.com   (Vaccine Formulation)

Limited Edit Access:
  • scientist2@bioprocess.com        (Vaccine Formulation only)

Read-Only Access:
  • viewer@bioprocess.com            (Both projects, read-only)

Admin Access:
  • admin@bioprocess.com             (Full system)

EOF
