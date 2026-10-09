import { format } from "date-fns";
import { NavLink } from "react-router-dom";
import { useEffect, useState } from "react";
import { IconCross } from "@humansignal/icons";
import { Userpic, Button, Select, useToast } from "@humansignal/ui";
import { useAuth } from "@humansignal/core/providers/AuthProvider";
import {
  MEMBER_ROLE_LABELS,
  MEMBER_ROLE_MANAGERS,
  MEMBER_ROLE_OPTIONS,
} from "@humansignal/core/lib/utils/member-roles";
import { useAPI } from "../../../providers/ApiProvider";
import { cn } from "../../../utils/bem";
import "./SelectedUser.scss";

const UserProjectsLinks = ({ projects }) => {
  return (
    <div className={cn("user-info").elem("links-list").toClassName()}>
      {projects.map((project) => (
        <NavLink
          className={cn("user-info").elem("project-link").toClassName()}
          key={`project-${project.id}`}
          to={`/projects/${project.id}`}
          data-external
        >
          {project.title}
        </NavLink>
      ))}
    </div>
  );
};

export const SelectedUser = ({ user, onRoleUpdated, onClose }) => {
  const api = useAPI();
  const toast = useToast();
  const { user: currentUser } = useAuth();
  const [role, setRole] = useState(user.role);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setRole(user.role);
  }, [user.id, user.role]);

  const fullName = [user.first_name, user.last_name]
    .filter((n) => !!n)
    .join(" ")
    .trim();

  const canManageRoles = MEMBER_ROLE_MANAGERS.includes(currentUser?.role);

  const updateRole = async (newRole) => {
    if (isSaving || newRole === role) return;

    setIsSaving(true);
    const result = await api.callApi("updateMembership", {
      params: {
        pk: currentUser?.active_organization ?? 1,
        userPk: user.id,
      },
      body: { role: newRole },
    });

    setIsSaving(false);

    if (result && !result.error) {
      setRole(newRole);
      onRoleUpdated?.(user.id, newRole);
      toast.show({ message: "Member role updated" });
    }
  };

  return (
    <div className={cn("user-info").toClassName()}>
      <Button
        look="string"
        onClick={onClose}
        className="absolute top-[20px] right-[24px]"
        aria-label="Close user details"
      >
        <IconCross />
      </Button>

      <div className={cn("user-info").elem("header").toClassName()}>
        <Userpic user={user} style={{ width: 64, height: 64, fontSize: 28 }} />
        <div className={cn("user-info").elem("info-wrapper").toClassName()}>
          {fullName && <div className={cn("user-info").elem("full-name").toClassName()}>{fullName}</div>}
          <p className={cn("user-info").elem("email").toClassName()}>{user.email}</p>
        </div>
      </div>

      {user.phone && (
        <div className={cn("user-info").elem("section").toClassName()}>
          <a href={`tel:${user.phone}`}>{user.phone}</a>
        </div>
      )}

      <div className={cn("user-info").elem("section").toClassName()}>
        <div className={cn("user-info").elem("section-title").toClassName()}>Role</div>
        {canManageRoles ? (
          <Select
            value={role}
            options={MEMBER_ROLE_OPTIONS}
            onChange={updateRole}
            disabled={isSaving}
            placeholder="Select a role"
          />
        ) : (
          <p>{MEMBER_ROLE_LABELS[role] ?? role ?? "—"}</p>
        )}
      </div>

      {!!user.created_projects.length && (
        <div className={cn("user-info").elem("section").toClassName()}>
          <div className={cn("user-info").elem("section-title").toClassName()}>Created Projects</div>

          <UserProjectsLinks projects={user.created_projects} />
        </div>
      )}

      {!!user.contributed_to_projects.length && (
        <div className={cn("user-info").elem("section").toClassName()}>
          <div className={cn("user-info").elem("section-title").toClassName()}>Contributed to</div>

          <UserProjectsLinks projects={user.contributed_to_projects} />
        </div>
      )}

      <p className={cn("user-info").elem("last-active").toClassName()}>
        Last activity on: {format(new Date(user.last_activity), "dd MMM yyyy, KK:mm a")}
      </p>
    </div>
  );
};
