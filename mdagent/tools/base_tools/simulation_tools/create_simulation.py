import textwrap
from typing import Optional

from langchain import LLMChain, PromptTemplate
from langchain.base_language import BaseLanguageModel
from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from mdagent.utils import PathRegistry


class ModifyScriptUtils:
    def __init__(self, llm):
        llm = llm

    Examples = [
        """
from openmm.app import *
from openmm import *
from openmm.unit import *
from sys import stdout

pdb = PDBFile("1AKI.pdb")

#We need to define the forcefield we want to use.
#We will use the Amber14 forcefield and the TIP3P-FB water model.

# Specify the forcefield
forcefield = ForceField('amber14-all.xml', 'amber14/tip3pfb.xml')

#This PDB file contains some crystal water molecules which we want to strip out.
#This can be done using the Modeller class. We also add in any missing H atoms.
modeller = Modeller(pdb.topology, pdb.positions)
modeller.deleteWater()
residues=modeller.addHydrogens(forcefield)

#We can use the addSolvent method to add water molecules
modeller.addSolvent(forcefield, padding=1.0*nanometer)

#We now need to combine our molecular topology and the forcefield
#to create a complete description of the system. This is done using
# the ForceField object’s createSystem() function. We then create the integrator,
# and combine the integrator and system to create the Simulation object.
# Finally we set the initial atomic positions.

system = forcefield.createSystem(modeller.topology, nonbondedMethod=PME,
nonbondedCutoff=1.0*nanometer, constraints=HBonds)
integrator = LangevinMiddleIntegrator(300*kelvin, 1/picosecond, 0.004*picoseconds)
simulation = Simulation(modeller.topology, system, integrator)
simulation.context.setPositions(modeller.positions)

#It is a good idea to run local energy minimization at the start of a simulation,
# since the coordinates in the PDB file might produce very large forces

print("Minimizing energy")
simulation.minimizeEnergy()

#To get output from our simulation we can add reporters.
# We use PDBReporter to write the coorinates every 1000 timesteps
# to “output.pdb” and we use StateDataReporter to print the timestep,
# potential energy, temperature, and volume to the screen and to
# a file called “md_log.txt”.

simulation.reporters.append(PDBReporter('output.pdb', 1000))
simulation.reporters.append(StateDataReporter(stdout, 1000, step=True,
        potentialEnergy=True, temperature=True, volume=True))
simulation.reporters.append(StateDataReporter("md_log.txt", 100, step=True,
        potentialEnergy=True, temperature=True, volume=True))

#We are using a Langevin integrator which means we are simulating in the NVT ensemble.
# To equilibrate the temperature we just need to run the
# simulation for a number of timesteps.
print("Running NVT")
simulation.step(10000)

#To run our simulation in the NPT ensemble we
# need to add in a barostat to control the pressure. We can use MonteCarloBarostat
system.addForce(MonteCarloBarostat(1*bar, 300*kelvin))
simulation.context.reinitialize(preserveState=True)


print("Running NPT")
simulation.step(10000)
        """
    ]

    def _prompt_summary(self, query: str, llm: BaseLanguageModel = None):
        if not llm:
            raise ValueError("No language model provided at ModifyScriptTool")

        prompt_template = """ You're an expert programmer and in molecular dynamics.
        Your job is to make a script to make a simmulatiuon.
        in openmm.
        Youre starting point is a base script that runs a protein on its own.
        The protein itself doesnt require more preperation.
        The forcefields, integrator, and constraints are already set up for you.
        You need to add lines to fullfill the user requirement.
        Your answer has to be the modified script.
        Your answer should be a python script.
        Dont use ''' to comment out the code, use # instead.
        Describe your thoughts and changes before you start writing the script.
        The script will be rum as it is, so make it completely.

        The format should be as follows:
        THOUGHTS: (Your thoughts as an openmm expert with the base script and the query)
        CHANGES:(what modifications youre doing to the script)
        SCRIPT: (The COMPLETE modified script)
        FINAL THOUGHTS: (Optional, Any final thoughts or comments
        you have about the script)


        Base_SCRIPT:
        {base_script}
        Question: {query}
        """

        prompt = PromptTemplate(
            template=prompt_template, input_variables=["base_script", "query"]
        )
        llm_chain = LLMChain(prompt=prompt, llm=llm)

        return llm_chain.invoke(query)

        # Remove leading spaces for proper formatting

    def remove_leading_spaces(self, text):
        lines = text.split("\n")
        stripped_lines = [line.lstrip() for line in lines]
        return "\n".join(stripped_lines)


class ModifyScriptInput(BaseModel):
    query: str = Field(..., description="Simmulation required by the user")
    script: str = Field(..., description=" path to the base script file")


class ModifyBaseSimulationScriptTool(BaseTool):
    name: str = "ModifyScriptTool"
    description: str = """This tool takes a base simulation script and a user
    requirement and returns a modified script. """

    args_schema = ModifyScriptInput
    llm: Optional[BaseLanguageModel]
    path_registry: Optional[PathRegistry]

    def __init__(self, path_registry: Optional[PathRegistry], llm: BaseLanguageModel):
        super().__init__()
        self.path_registry = path_registry
        self.llm = llm

    def _run(self, **input):
        base_script_path = input.get("script")
        if not base_script_path:
            return """No script provided. The keys for the input are:
             'query' and 'script'"""
        with open(base_script_path, "r") as file:
            base_script = file.read()
        base_script = "".join(base_script)
        utils = ModifyScriptUtils()

        description = input.get("query")
        answer = utils._prompt_summary(
            query={"base_script": base_script, "query": description}, llm=self.llm
        )
        script = answer["text"]
        thoughts, new_script = script.split("SCRIPT:")
        script_content = utils.remove_leading_spaces(new_script)
        if "FINAL THOUGHTS:" in script_content:
            script_content, final_thoughts = script_content.split("FINAL THOUGHTS:")
        # replace ''' with #
        script_content = script_content.replace("```", "#")
        script_content = textwrap.dedent(script_content).strip()
        # Write to file
        filename = "modified_simul.py"
        with open(filename, "w") as file:
            file.write(script_content)

        self.path_registry.map_path(filename, filename, description)
        return "Script modified successfully"

    async def _arun(self, query) -> str:
        """Use the tool asynchronously."""
        raise NotImplementedError("this tool does not support async")