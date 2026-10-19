export const isAdminRole = (role) => role === "admin" || role === "super_admin";
export const isSuperAdmin = (role) => role === "super_admin";
export const isIctAdmin = (role) => role === "ict_admin";
export const isCampusAdmin = (role) => role === "campus_admin";
// ICT Admin and Campus Admin are tied to one campus.
export const isCampusBound = (role) => role === "ict_admin" || role === "campus_admin";
// Admin, Super Admin and Campus Admin (Campus Admin only for their own campus).
export const isManagerRole = (role) => isAdminRole(role) || role === "campus_admin";
export const isLeader = (role) => role === "leader";
// Leaders can read everything but never change anything.
export const canWrite = (role) => role !== "leader";
// ICT admins manage assets only in the ICT categories of their own campus (the server enforces the same rule).
export const ICT_CATEGORIES = ["IT Equipment", "AV Equipment", "Music Equipment"];
export const canManageAsset = (user, asset) =>
  user?.role === "super_admin" ||
  (user?.role === "admin" && !!asset && !ICT_CATEGORIES.includes(asset.category)) ||   // Admin: every asset except ICT / media
  (isCampusBound(user?.role) && !!asset && (user.role === "campus_admin" || ICT_CATEGORIES.includes(asset.category)) && !!user.campus && user.campus === (asset.campus || ""));
