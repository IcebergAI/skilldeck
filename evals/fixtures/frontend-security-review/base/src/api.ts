// Member profiles are public: any signed-in member can view any other
// member's profile page. Members write their own display name, avatar URL and
// bio on the settings page, and the API returns them as stored.
export interface Profile {
  id: string;
  displayName: string;
  avatarUrl: string;
  bio: string;
}

export async function fetchProfile(id: string): Promise<Profile> {
  const res = await fetch(`/api/members/${encodeURIComponent(id)}`, {
    credentials: "same-origin",
  });
  if (!res.ok) {
    throw new Error(`profile ${id}: HTTP ${res.status}`);
  }
  return res.json();
}
