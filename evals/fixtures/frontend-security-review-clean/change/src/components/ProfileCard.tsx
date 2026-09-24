import DOMPurify from "dompurify";

import type { Profile } from "../api";

// Bios may use bold, italics, paragraphs and links, and nothing else.
const BIO_ALLOWED = {
  ALLOWED_TAGS: ["a", "b", "br", "em", "i", "p", "strong"],
  ALLOWED_ATTR: ["href"],
};

export function ProfileCard({ profile }: { profile: Profile }) {
  // bioHtml is member-written, so sanitize it here, at the sink, every render
  const bio = DOMPurify.sanitize(profile.bioHtml, BIO_ALLOWED);
  return (
    <section className="profile-card">
      <img className="avatar" src={profile.avatarUrl} alt="" width={96} height={96} />
      <h1>{profile.displayName}</h1>
      <div className="bio" dangerouslySetInnerHTML={{ __html: bio }} />
    </section>
  );
}
