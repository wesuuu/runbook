#!/usr/bin/env python3
"""
Verification script for runs feature.
Tests the complete workflow: create project -> protocol -> run
"""

import asyncio
import sys
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, "/home/wesuuu/Code/trellisbio/backend")

from app.db.session import AsyncSessionLocal
from app.models.iam import (
    Organization,
    OrganizationMember,
    User,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
)
from app.models.science import Project, Protocol, Run, ProtocolRole, RunRoleAssignment
from app.core.security import hash_password
from sqlalchemy import select


async def main():
    """Run verification workflow."""
    db = AsyncSessionLocal()

    print("=" * 60)
    print("RUNS FEATURE VERIFICATION TEST")
    print("=" * 60)

    try:
        # 1. Create test user
        print("\n1. Creating test user...")
        user = User(
            email=f"test-{uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("testpass123"),
            full_name="Test User",
        )
        db.add(user)
        await db.flush()
        print(f"   ✓ User created: {user.id}")

        # 2. Create organization
        print("\n2. Creating organization...")
        org = Organization(name="Test Organization")
        db.add(org)
        await db.flush()
        db.add(
            OrganizationMember(
                user_id=user.id, organization_id=org.id, role="ADMIN"
            )
        )
        await db.flush()
        print(f"   ✓ Organization created: {org.id}")

        # 3. Create project
        print("\n3. Creating project...")
        project = Project(
            name="Test Project",
            organization_id=org.id,
            owner_type="USER",
            owner_id=user.id,
        )
        db.add(project)
        await db.flush()
        db.add(
            ObjectPermission(
                principal_type=PrincipalType.USER,
                principal_id=user.id,
                object_type=ObjectType.PROJECT.value,
                object_id=project.id,
                permission_level=PermissionLevel.ADMIN.value,
            )
        )
        await db.flush()
        print(f"   ✓ Project created: {project.id}")

        # 4. Create protocol with roles
        print("\n4. Creating protocol with roles...")
        protocol = Protocol(
            name="Test Protocol",
            project_id=project.id,
            graph={
                "nodes": [
                    {
                        "id": "lane-1",
                        "type": "swimLane",
                        "position": {"x": 0, "y": 0},
                        "data": {"label": "Scientist"},
                        "style": "width: 400px; height: 200px;",
                    },
                    {
                        "id": "node-1",
                        "type": "unitOp",
                        "position": {"x": 50, "y": 50},
                        "parentId": "lane-1",
                        "data": {
                            "label": "Mix Reagents",
                            "category": "Media Prep",
                            "description": "Combine buffer and media",
                            "duration_min": 30,
                            "params": {"volume_L": 10},
                        },
                    },
                ],
                "edges": [],
                "layout": "horizontal",
                "handleOrientation": "horizontal",
            },
        )
        db.add(protocol)
        await db.flush()

        role = ProtocolRole(
            protocol_id=protocol.id, name="Scientist", color="#3b82f6", sort_order=0
        )
        db.add(role)
        await db.flush()
        print(f"   ✓ Protocol created: {protocol.id}")
        print(f"   ✓ Role created: {role.id}")

        # 5. Create run from protocol
        print("\n5. Creating run from protocol...")
        run_obj = Run(
            name="Test Run",
            project_id=project.id,
            protocol_id=protocol.id,
            status="PLANNED",
            graph=protocol.graph.copy(),
            execution_data={},
        )
        db.add(run_obj)
        await db.flush()
        print(f"   ✓ Run created: {run_obj.id}")
        print(f"   ✓ Status: {run_obj.status}")
        print(f"   ✓ Graph nodes: {len(run_obj.graph.get('nodes', []))}")

        # 6. Test role assignment
        print("\n6. Testing role assignment...")
        assignment = RunRoleAssignment(
            run_id=run_obj.id,
            lane_node_id="lane-1",
            role_name="Scientist",
            user_id=user.id,
        )
        db.add(assignment)
        await db.flush()
        print(f"   ✓ Role assignment created: {assignment.id}")
        print(f"   ✓ Assigned user: {assignment.user_id}")
        print(f"   ✓ Assigned lane: {assignment.lane_node_id}")

        # 7. Verify all relationships
        print("\n7. Verifying relationships...")

        # Check run is linked to protocol
        result = await db.execute(
            select(Run).where(Run.id == run_obj.id)
        )
        fetched_run = result.scalar_one()
        assert fetched_run.protocol_id == protocol.id
        print("   ✓ Run linked to protocol")

        # Check role assignments
        result = await db.execute(
            select(RunRoleAssignment).where(
                RunRoleAssignment.run_id == run_obj.id
            )
        )
        assignments = result.scalars().all()
        assert len(assignments) == 1
        print(f"   ✓ Role assignments exist: {len(assignments)}")

        # Check protocol has roles
        result = await db.execute(
            select(ProtocolRole).where(ProtocolRole.protocol_id == protocol.id)
        )
        roles = result.scalars().all()
        assert len(roles) == 1
        print(f"   ✓ Protocol roles exist: {len(roles)}")

        print("\n" + "=" * 60)
        print("✅ ALL VERIFICATION TESTS PASSED!")
        print("=" * 60)
        print("\nSummary:")
        print(f"  User ID:          {user.id}")
        print(f"  Organization ID:  {org.id}")
        print(f"  Project ID:       {project.id}")
        print(f"  Protocol ID:      {protocol.id}")
        print(f"  Run ID:           {run_obj.id}")
        print(f"  Role ID:          {role.id}")
        print(f"  Assignment ID:    {assignment.id}")
        print("\nYou can now test in the browser with:")
        print(f"  1. Login with: test-xxx@example.com / testpass123")
        print(f"  2. Navigate to the project")
        print(f"  3. Create a new run (this should work without 500 error)")

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
