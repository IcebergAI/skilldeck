import type { Profile } from "../api";

export function ProfileCard({ profile }: { profile: Profile }) {
  return (
    <section className="profile-card">
      <img className="avatar" src={profile.avatarUrl} alt="" width={96} height={96} />
      <h1>{profile.displayName}</h1>
      <p className="bio">{profile.bio}</p>
    </section>
  );
}
