export const isAdminRole = (role) => role === "admin" || role === "super_admin";
export const isSuperAdmin = (role) => role === "super_admin";
export const isIctAdmin = (role) => role === "ict_admin";
export const isLeader = (role) => role === "leader";
// Leaders can read everything but never change anything.
export const canWrite = (role) => role !== "leader";
