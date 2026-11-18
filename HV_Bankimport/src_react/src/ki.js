export const isOpenKi = (row) => ["Pending", "Approved"].includes(row?.ki?.status);

export const isAdjustedBooking = (ki) =>
	ki?.status === "Rejected" && ki.decision?.category === "adjusted_booked";

export function kiBindings(ki) {
	return ki.steps.filter((step) => step.status !== "Succeeded")
		.map(({ proposal, revision, hash }) => ({ id: proposal, revision, hash }));
}

export function kiError(error) {
	return Number(error.status) === 409
		? "Die Daten haben sich gleichzeitig geändert. Bitte erneut versuchen."
		: error.message || String(error);
}
