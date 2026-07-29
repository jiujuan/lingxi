type IconProps = {
  className?: string;
};

export function EditIcon({ className }: IconProps) {
  return (
    <svg aria-hidden="true" className={className} fill="none" viewBox="0 0 24 24">
      <path
        d="M4 16.75V20h3.25L18.4 8.85l-3.25-3.25L4 16.75Z"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path d="m13.9 6.85 3.25 3.25" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

export function TrashIcon({ className }: IconProps) {
  return (
    <svg aria-hidden="true" className={className} fill="none" viewBox="0 0 24 24">
      <path d="M4 7h16" stroke="currentColor" strokeWidth="1.8" />
      <path d="M10 11v5m4-5v5" stroke="currentColor" strokeWidth="1.8" />
      <path d="m9 7 1-3h4l1 3m-9 0 1 13h10l1-13" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
