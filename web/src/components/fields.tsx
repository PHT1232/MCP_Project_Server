import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

const CONTROL_CLASS =
  "rounded-small border border-fey-smoke bg-fey-obsidian px-14 py-10 text-body text-fey-white outline-none transition-colors focus:border-fey-mist disabled:opacity-40";

interface LabelledProps {
  label: string;
  children: ReactNode;
  hint?: string;
}

/** A caption-labelled control wrapper — the shared field layout. */
export function Field({ label, children, hint }: LabelledProps): ReactNode {
  return (
    <label className="flex flex-col gap-6 text-caption uppercase text-fey-graphite">
      {label}
      {children}
      {hint !== undefined && (
        <span className="text-caption normal-case text-fey-graphite">{hint}</span>
      )}
    </label>
  );
}

type TextInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className">;

export function TextInput(props: TextInputProps): ReactNode {
  return <input className={CONTROL_CLASS} {...props} />;
}

type TextAreaProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "className">;

export function TextArea(props: TextAreaProps): ReactNode {
  return <textarea className={CONTROL_CLASS} {...props} />;
}

type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "className"> & {
  children: ReactNode;
};

export function Select({ children, ...rest }: SelectProps): ReactNode {
  return (
    <select className={CONTROL_CLASS} {...rest}>
      {children}
    </select>
  );
}
