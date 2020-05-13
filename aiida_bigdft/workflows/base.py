"""
Basic wrapping workchain on a BigDFT computation.

"""
from aiida.common.extendeddicts import AttributeDict
from aiida.engine import BaseRestartWorkChain, process_handler, while_, ExitCode
from aiida.plugins import CalculationFactory

from aiida.engine.processes.workchains.utils import process_handler, ProcessHandlerReport

from futile import YamlIO


BigDFTCalculation = CalculationFactory('bigdft')

class BigDFTBaseWorkChain(BaseRestartWorkChain):

    _process_class = BigDFTCalculation

    @classmethod
    def define(cls, spec):
        super(BigDFTBaseWorkChain, cls).define(spec)
        spec.expose_inputs(BigDFTCalculation, namespace='bigdft')
        # spec.input('code', valid_type=orm.Code, help='The BigDFT code.')
        spec.outline(
            cls.setup,
            while_(cls.should_run_process)(
                cls.run_process,
                cls.inspect_process,
            ),
            cls.results,
        )
        spec.expose_outputs(BigDFTCalculation)
        spec.exit_code(100, 'ERROR_INPUT',
                       message='BigDFT input error')
        spec.exit_code(200, 'ERROR_RUNTIME',
                       message='BigDFT runtime error')

# TODO : read debug files and report errors. Restart when possible.
    @process_handler(priority=600)
    def check_debug_output(self, calculation):
        repo = calculation.outputs.retrieved._repository._get_base_folder()
        try:
            repo.get_abs_path('debug', check_existence=True)
        except OSError:
            return
        debug_folder = repo.get_subfolder('debug')
        # debug folder exists, error probably happened.
        if self.ctx.inputs.metadata.options.jobname is not None:
            jobname = self.ctx.inputs.metadata.options.jobname
        else:
            jobname = 'BigDFT job'
        logs = []
        posout_list = debug_folder.get_content_list(pattern="bigdft-err*")
        for filename in posout_list:
            log = YamlIO.load(debug_folder.get_abs_path(filename), doc_lists=True, safe_mode=True)
            err = log[0].get('BIGDFT_INPUT_VARIABLES_ERROR')
            if err is not None:
                self.report('{}<{}> input error : {} Id: {}'.
                            format(jobname, calculation.pk, err['Message'], err['Id']))
                return ProcessHandlerReport(True, ExitCode(100))
            err = log[0].get('BIGDFT_RUNTIME_ERROR')
            if err is not None:
                self.report('{}<{}> runtime error : {} Id: {}'.
                            format(jobname, calculation.pk, err['Message'], err['Id']))
                return ProcessHandlerReport(True, ExitCode(200))



    @process_handler(priority=500)
    def finish(self, node):
        if node.is_finished_ok:
            if self.ctx.inputs.metadata.options.jobname is not None:
                jobname = self.ctx.inputs.metadata.options.jobname
            else:
                jobname = 'BigDFT job'
            self.report('{}<{}> completed successfully'.
                        format(jobname, node.pk))
            self.ctx.restart_calc = node
            self.ctx.is_finished = True

    def setup(self):
        super().setup()
        self.ctx.inputs = AttributeDict(self.exposed_inputs(BigDFTCalculation,
                                                            'bigdft'))
        # self.ctx.inputs.code = self.inputs.code



    
