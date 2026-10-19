export const isAdminRole = (role) => role === "admin" || role === "super_admin";
export const isSuperAdmin = (role) => role === "super_admin";
export const isIctAdmin = (role) => role === "ict_admin";
export const isLeader = (role) => role === "leader";
// Leaders can read everything but never change anything.
export const canWrite = (role) => role !== "leader";
// ICT admins manage assets only in the ICT categories of their own campus (the server enforces the same rule).
export const ICT_CATEGORIES = ["IT Equipment", "AV Equipment", "Music Equipment"];
export const canManageAsset = (user, asset) =>
  isAdminRole(user?.role) ||
  (user?.role === "ict_admin" && !!asset && ICT_CATEGORIES.includes(asset.category) && !!user.campus && user.campus === (asset.campus || ""));
