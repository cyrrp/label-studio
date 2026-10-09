/**
 * Organization member roles — mirrors `OrganizationMemberRole` in
 * `organizations/models.py` on the backend (OW/AD/MA/RE/AN).
 */
export type MemberRole = "OW" | "AD" | "MA" | "RE" | "AN";

export const MEMBER_ROLE_LABELS: Record<MemberRole, string> = {
  OW: "Owner",
  AD: "Administrator",
  MA: "Manager",
  RE: "Reviewer",
  AN: "Annotator",
};

export const MEMBER_ROLE_OPTIONS = (Object.keys(MEMBER_ROLE_LABELS) as MemberRole[]).map((value) => ({
  value,
  label: MEMBER_ROLE_LABELS[value],
}));

/** Roles allowed to change other members' roles */
export const MEMBER_ROLE_MANAGERS: MemberRole[] = ["OW", "AD"];
