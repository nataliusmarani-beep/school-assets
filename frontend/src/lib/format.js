// Owner labels are stored as "Name — Room — Campus"; lists and cards show the person's name only.
export const ownerName = (label) => (label || "").split(" — ")[0].trim();
