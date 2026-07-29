import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState, Loading, Status } from "../components/common/States";
import type { Task } from "../types";
const queues = [
  "08_Info_Required",
  "03_Cornerstone_Bonds",
  "04_NMLS",
  "05_Regulators",
  "06_Invoices",
  "07_Proof_Received",
  "09_Internal_Followups",
];
export function TaskBoardPage() {
  const q = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api<Task[]>("/licensing-tasks"),
  });
  if (q.isLoading) return <Loading label="Loading task board" />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <main>
      <div className="page-title">
        <div>
          <span className="eyebrow">Approved work only</span>
          <h1>Licensing task board</h1>
          <p>
            Assignments, deadlines, and requested information from reviewed
            classifications.
          </p>
        </div>
      </div>
      <div className="board">
        {queues.map((queue) => {
          const tasks = q.data?.filter((t) => t.queue === queue) ?? [];
          return (
            <section className="board-column" key={queue}>
              <header>
                <span>{queue.replace(/^\d+_/, "").replaceAll("_", " ")}</span>
                <b>{tasks.length}</b>
              </header>
              {tasks.map((task) => (
                <Link
                  className="task-card"
                  key={task.id}
                  to={`/tasks/${task.id}`}
                >
                  <div>
                    <span className="vendor">{task.vendor ?? "General"}</span>
                    <Status value={task.status} />
                  </div>
                  <h3>{task.title}</h3>
                  <p>{task.assigned_to ?? "Unassigned"}</p>
                  <footer>
                    <span>
                      {task.due_date ? `Due ${task.due_date}` : "No due date"}
                    </span>
                    <b>{task.priority}</b>
                  </footer>
                </Link>
              ))}
              {tasks.length === 0 && (
                <div className="column-empty">No active work</div>
              )}
            </section>
          );
        })}
      </div>
    </main>
  );
}
