"""
AgentCoordinator: Orchestrates the multi-agent pipeline
Controls the flow: CollectorAgent -> VerifierAgent -> LogbookAgent -> RewardAgent -> ComplianceAgent
"""

from agents.collector_agent import CollectorAgent
from agents.verifier_agent import VerifierAgent
from agents.logbook_agent import LogbookAgent
from agents.reward_agent import RewardAgent
from agents.compliance_agent import ComplianceAgent


class AgentCoordinator:
    """
    Coordinates a pipeline of agents to process activities.
    Each agent runs in sequence and can stop the pipeline if needed.
    """
    
    PIPELINE = [
        CollectorAgent(),
        VerifierAgent(),
        LogbookAgent(),
        RewardAgent(),
        ComplianceAgent(),
    ]

    def run_pipeline(self, activity_id: int) -> bool:
        """
        Run all agents in the pipeline for a given activity.
        
        Args:
            activity_id: The ID of the activity to process
            
        Returns:
            True if pipeline completed successfully, False if stopped/rejected
        """
        print(f"\n{'='*80}", flush=True)
        print(f"[COORDINATOR] Starting pipeline for activity_id={activity_id}", flush=True)
        print(f"[COORDINATOR] Pipeline stages: {' -> '.join(agent.name for agent in self.PIPELINE)}", flush=True)
        print(f"{'='*80}\n", flush=True)

        for i, agent in enumerate(self.PIPELINE, 1):
            print(f"[COORDINATOR] [{i}/{len(self.PIPELINE)}] Running {agent.name}...", flush=True)
            
            try:
                result = agent.process(activity_id)
                
                if result is False:
                    print(f"[COORDINATOR] ❌ {agent.name} rejected/failed the activity", flush=True)
                    print(f"[COORDINATOR] Pipeline stopped", flush=True)
                    print(f"{'='*80}\n", flush=True)
                    return False
                else:
                    print(f"[COORDINATOR] ✓ {agent.name} completed successfully", flush=True)
                    
            except Exception as e:
                print(f"[COORDINATOR ERROR] {agent.name} raised exception: {type(e).__name__}: {str(e)}", flush=True)
                print(f"[COORDINATOR] Pipeline stopped due to exception", flush=True)
                import traceback
                traceback.print_exc()
                print(f"{'='*80}\n", flush=True)
                return False

        print(f"[COORDINATOR] ✅ Pipeline completed successfully for activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)
        return True
