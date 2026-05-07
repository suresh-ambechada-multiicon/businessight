import { useMemo, memo, useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  AreaChart,
  Area,
  RadarChart,
  Radar,
  ScatterChart,
  Scatter,
  ComposedChart,
  RadialBarChart,
  RadialBar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  Label,
} from "recharts";
import { formatNumber, formatXAxisDate } from "../utils/formatters";

const COLORS = [
  "#ef4444",
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
  "#06b6d4",
  "#84cc16",
];

interface ChartDisplayProps {
  type: string;
  config: any;
}

const truncateLabel = (label: any) => {
  if (typeof label !== "string") return label;
  return label.length > 20 ? label.substring(0, 17) + "..." : label;
};

export const ChartDisplay = memo(({ type, config }: ChartDisplayProps) => {
  const [hiddenDatasets, setHiddenDatasets] = useState<Record<string, boolean>>({});
  const data = config.data;

  const toggleDataset = (e: any) => {
    const { dataKey } = e;
    setHiddenDatasets(prev => ({
      ...prev,
      [dataKey]: !prev[dataKey]
    }));
  };

  const chartData = useMemo(() => {
    if (!data || !data.labels || !data.datasets) return [];
    return data.labels.map((label: string, index: number) => {
      const item: any = { name: label };
      data.datasets.forEach((ds: any) => {
        item[ds.label] = ds.data[index];
      });
      return item;
    });
  }, [data]);

  if (chartData.length === 0) return null;

  const tooltipStyle = {
    backgroundColor: "var(--bg-surface)",
    borderColor: "var(--border-color)",
    color: "var(--text-primary)",
    borderRadius: "8px",
    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
  };

  const isLargeDataset = chartData.length > 15;
  const hasLongLabels = chartData.some((d: any) => String(d.name).length > 15);


  const xLabel = config.x_label || "Category";
  const yLabel = config.y_label || "Metric";

  const xAxisProps: any = {
    dataKey: "name",
    tickFormatter: (val: any) => {
      const formatted = formatXAxisDate(val);
      return truncateLabel(formatted);
    },
    tick: { fill: "var(--text-secondary)", fontSize: 10 },
    interval: isLargeDataset ? "preserveStartEnd" : 0,
    angle: (isLargeDataset || hasLongLabels) ? -45 : 0,
    textAnchor: (isLargeDataset || hasLongLabels) ? "end" : "middle",
    height: (isLargeDataset || hasLongLabels) ? 100 : 40,
    stroke: "var(--border-color)",
    strokeWidth: 1.5,
  };

  const chartMargin = {
    top: 10,
    right: 20,
    left: 60,
    bottom: (isLargeDataset || hasLongLabels) ? 80 : 40
  };

  const xAxisLabel = (
    <Label
      value={xLabel}
      offset={-10}
      position="insideBottom"
      fill="var(--text-primary)"
      fontSize={10}
      className="chart-axis-label"
    />
  );

  const yAxisLabel = (
    <Label
      value={yLabel}
      angle={-90}
      position="insideLeft"
      offset={-45}
      style={{ textAnchor: 'middle', fill: 'var(--text-primary)', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', opacity: 0.6 }}
    />
  );

  const legendProps: any = {
    onClick: toggleDataset,
    verticalAlign: "top",
    align: "center",
    iconType: "circle",
    className: 'chart-legend-wrapper'
  };

  if (type === "bar" || type === "stacked-bar") {
    return (
      <ResponsiveContainer width="100%" height={isLargeDataset || hasLongLabels ? 420 : 360}>
        <BarChart data={chartData} margin={chartMargin}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis {...xAxisProps}>{xAxisLabel}</XAxis>
          <YAxis
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
            domain={[0, "auto"]}
            stroke="var(--border-color)"
            strokeWidth={1}
          >
            {yAxisLabel}
          </YAxis>
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend {...legendProps} />
          {data.datasets.map((ds: any, i: number) => (
            <Bar
              key={ds.label}
              dataKey={ds.label}
              hide={hiddenDatasets[ds.label]}
              stackId={type === "stacked-bar" ? "a" : undefined}
              fill={COLORS[i % COLORS.length]}
              radius={type === "stacked-bar" ? [0, 0, 0, 0] : [4, 4, 0, 0]}
              isAnimationActive={false}
              maxBarSize={50}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (type === "line") {
    return (
      <ResponsiveContainer width="100%" height={isLargeDataset || hasLongLabels ? 420 : 360}>
        <LineChart data={chartData} margin={chartMargin}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis {...xAxisProps}>{xAxisLabel}</XAxis>
          <YAxis
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
            domain={["auto", "auto"]}
            stroke="var(--border-color)"
            strokeWidth={1}
          >
            {yAxisLabel}
          </YAxis>
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend {...legendProps} />
          {data.datasets.map((ds: any, i: number) => (
            <Line
              key={ds.label}
              type="monotone"
              dataKey={ds.label}
              hide={hiddenDatasets[ds.label]}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={2}
              dot={!isLargeDataset}
              activeDot={{ r: 6 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (type === "area" || type === "stacked-area") {
    return (
      <ResponsiveContainer width="100%" height={isLargeDataset || hasLongLabels ? 420 : 360}>
        <AreaChart data={chartData} margin={chartMargin}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis {...xAxisProps}>{xAxisLabel}</XAxis>
          <YAxis
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
            domain={[0, "auto"]}
            stroke="var(--border-color)"
            strokeWidth={1}
          >
            {yAxisLabel}
          </YAxis>
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend {...legendProps} />
          {data.datasets.map((ds: any, i: number) => (
            <Area
              key={ds.label}
              type="monotone"
              dataKey={ds.label}
              hide={hiddenDatasets[ds.label]}
              stackId={type === "stacked-area" ? "1" : undefined}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.3}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  if (type === "composed") {
    return (
      <ResponsiveContainer width="100%" height={isLargeDataset || hasLongLabels ? 420 : 360}>
        <ComposedChart data={chartData} margin={chartMargin}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis {...xAxisProps}>{xAxisLabel}</XAxis>
          <YAxis tickFormatter={formatNumber} tick={{ fill: "var(--text-secondary)", fontSize: 10 }} stroke="var(--border-color)" strokeWidth={1}>{yAxisLabel}</YAxis>
          <Tooltip contentStyle={tooltipStyle} />
          <Legend {...legendProps} />
          {data.datasets.map((ds: any, i: number) =>
            i === 0 ? (
              <Bar key={ds.label} dataKey={ds.label} hide={hiddenDatasets[ds.label]} fill={COLORS[i % COLORS.length]} radius={[4, 4, 0, 0]} maxBarSize={40} isAnimationActive={false} />
            ) : (
              <Line key={ds.label} type="monotone" dataKey={ds.label} hide={hiddenDatasets[ds.label]} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} isAnimationActive={false} />
            )
          )}
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  if (type === "pie") {
    return (
      <ResponsiveContainer width="100%" height={350}>
        <PieChart>
          {data.datasets.map((ds: any, i: number) => {
            const isLast = i === data.datasets.length - 1;
            const outer = 100 - (i * 25);
            const inner = 100 - ((i + 1) * 25);
            return (
              <Pie
                key={ds.label}
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={data.datasets.length > 1 ? inner : 0}
                outerRadius={outer}
                paddingAngle={2}
                labelLine={!isLargeDataset && isLast}
                label={(!isLargeDataset && isLast) ? ({ name, percent }) =>
                  `${truncateLabel(name)}: ${(percent ? percent * 100 : 0).toFixed(0)}%` : false
                }
                dataKey={ds.label}
                nameKey="name"
                isAnimationActive={false}
                hide={hiddenDatasets[ds.label]}
              >
                {chartData.map((_entry: any, index: number) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={COLORS[(index + i) % COLORS.length]}
                  />
                ))}
              </Pie>
            );
          })}
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend {...legendProps} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (type === "radar") {
    return (
      <ResponsiveContainer width="100%" height={400}>
        <RadarChart cx="50%" cy="50%" outerRadius="70%" data={chartData}>
          <PolarGrid stroke="var(--border-color)" />
          <PolarAngleAxis dataKey="name" tickFormatter={truncateLabel} tick={{ fill: "var(--text-secondary)", fontSize: 10 }} />
          <PolarRadiusAxis tick={{ fill: "var(--text-secondary)", fontSize: 10 }} />
          {data.datasets.map((ds: any, i: number) => (
            <Radar
              key={ds.label}
              name={ds.label}
              dataKey={ds.label}
              hide={hiddenDatasets[ds.label]}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.6}
              isAnimationActive={false}
            />
          ))}
          <Tooltip formatter={formatNumber} contentStyle={tooltipStyle} />
          <Legend {...legendProps} />
        </RadarChart>
      </ResponsiveContainer>
    );
  }

  if (type === "radial") {
    return (
      <ResponsiveContainer width="100%" height={400}>
        <RadialBarChart cx="50%" cy="50%" innerRadius="10%" outerRadius="80%" barSize={isLargeDataset ? 5 : 15} data={chartData}>
          <RadialBar
            label={isLargeDataset ? false : { position: 'insideStart', fill: '#fff', formatter: truncateLabel }}
            background
            dataKey={data.datasets[0].label}
          >
            {chartData.map((_entry: any, index: number) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </RadialBar>
          {!isLargeDataset && <Legend iconSize={10} layout="vertical" verticalAlign="middle" wrapperStyle={{ right: 0 }} />}
          <Tooltip contentStyle={tooltipStyle} />
        </RadialBarChart>
      </ResponsiveContainer>
    );
  }

  if (type === "scatter") {
    return (
      <ResponsiveContainer width="100%" height={isLargeDataset || hasLongLabels ? 420 : 360}>
        <ScatterChart margin={chartMargin}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis {...xAxisProps} type="category" dataKey="x">{xAxisLabel}</XAxis>
          <YAxis
            type="number"
            tickFormatter={formatNumber}
            tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
            domain={["auto", "auto"]}
            stroke="var(--border-color)"
            strokeWidth={1}
          >
            {yAxisLabel}
          </YAxis>
          <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={tooltipStyle} />
          <Legend {...legendProps} />
          {data.datasets.map((ds: any, i: number) => (
            <Scatter
              key={ds.label}
              name={ds.label}
              data={data.labels.map((label: string, idx: number) => ({
                x: label,
                y: ds.data[idx],
              }))}
              hide={hiddenDatasets[ds.label]}
              fill={COLORS[i % COLORS.length]}
              isAnimationActive={false}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    );
  }


  return (
    <div className="report-text">Chart type {type} not supported yet.</div>
  );
});
