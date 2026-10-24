import { Slider } from 'radix-ui';
import { useId } from 'react';

/** Radix slider: keyboard (arrows, PageUp/Down, Home/End), touch-sized thumb, aria-valuetext in years. */
export function HorizonSlider({
  value,
  onChange,
  onCommit,
  min = 1,
  max = 30,
  label = 'Horizon',
}: {
  value: number;
  onChange: (v: number) => void;
  onCommit?: (v: number) => void;
  min?: number;
  max?: number;
  label?: string;
}) {
  const id = useId();
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-medium text-ink-900" id={id}>
          {label}
        </span>
        <span className="num text-sm font-medium text-ink-950" data-testid="horizon-value">
          {value} yrs
        </span>
      </div>
      <Slider.Root
        className="relative flex h-8 w-full touch-none items-center select-none"
        min={min}
        max={max}
        step={1}
        value={[value]}
        onValueChange={([v]) => onChange(v)}
        onValueCommit={([v]) => onCommit?.(v)}
        aria-labelledby={id}
      >
        <Slider.Track className="relative h-1.5 grow rounded-full bg-ink-100">
          <Slider.Range className="absolute h-full rounded-full bg-brand-500" />
        </Slider.Track>
        <Slider.Thumb
          aria-label={label}
          aria-valuetext={`${value} years`}
          data-testid="horizon-slider"
          className="block h-6 w-6 cursor-grab rounded-full border-2 border-brand-600 bg-surface shadow-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 active:cursor-grabbing sm:h-5 sm:w-5"
        />
      </Slider.Root>
      <div className="num flex justify-between text-[11px] text-ink-500">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}
