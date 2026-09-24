import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { fetchProfile, type Profile } from "../api";
import { ProfileCard } from "../components/ProfileCard";

export function ProfilePage() {
  const { memberId = "" } = useParams();
  const [profile, setProfile] = useState<Profile | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchProfile(memberId).then((p) => {
      if (!cancelled) setProfile(p);
    });
    return () => {
      cancelled = true;
    };
  }, [memberId]);

  return profile ? <ProfileCard profile={profile} /> : <p>Loading…</p>;
}
